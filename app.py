import os
import time
import json
import shutil
import datetime
import numpy as np

from dotenv import load_dotenv
load_dotenv()  # must run before importing groq_client, which reads keys at import time

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from database import SessionLocal, engine, Base
from models import (
    User, Ticket, Feedback, KnowledgeEntry,
    AnalyticsLog, ChatHistory, DocumentStore, DocumentChunk
)
from schemas import (
    SignupRequest, LoginRequest, ChangePasswordRequest, ChatRequest,
    FeedbackRequest, TicketCreateRequest, TicketUpdateRequest,
    TicketFeedbackRequest, RoleUpdateRequest, VoiceRequest
)
import rag
from groq_client import groq_client
import bcrypt
from jose import jwt, JWTError
import PyPDF2

app = FastAPI(title="SupportGPT", version="3.0")

# Create all tables
Base.metadata.create_all(bind=engine)


# ─── Secrets & config ───
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable must be set. Refusing to start with an "
        "insecure default — JWTs would otherwise be forgeable."
    )
ALGORITHM = "HS256"

SEED_DEMO_USERS = os.environ.get("SEED_DEMO_USERS", "false").strip().lower() == "true"

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:8000,http://127.0.0.1:8000"
    ).split(",")
    if origin.strip()
]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


# ─── Seed demo users (local/dev only, opt-in via SEED_DEMO_USERS=true) ───
def seed_users():
    if not SEED_DEMO_USERS:
        return
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "admin@123").first():
            db.add(User(
                username="admin@123", email="admin@system.local",
                password=hash_password("admin@123"), role="admin", points=9999
            ))
            print("Seeded demo admin user: admin@123 (SEED_DEMO_USERS=true — disable in production)")
        if not db.query(User).filter(User.username == "developer@123").first():
            db.add(User(
                username="developer@123", email="developer@system.local",
                password=hash_password("developer@123"), role="developer", points=5000
            ))
            print("Seeded demo developer user: developer@123 (SEED_DEMO_USERS=true — disable in production)")
        db.commit()
    finally:
        db.close()

seed_users()

# Ensure upload dirs exist
os.makedirs("docs", exist_ok=True)
os.makedirs("uploads", exist_ok=True)


# ─── DB Dependency ───
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── JWT Auth ───
def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ─── CORS ───
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Serve frontend static files ───
app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ─── Utility Functions ───
def log_analytics(db: Session, action: str, user_id=None, username=None, detail=None, response_time_ms=None):
    entry = AnalyticsLog(
        action=action,
        user_id=user_id,
        username=username,
        detail=detail,
        response_time_ms=response_time_ms
    )
    db.add(entry)
    db.commit()


KNOWLEDGE_SIMILARITY_THRESHOLD = 0.75


def find_knowledge(db: Session, question: str):
    """Search the curated knowledge base (positively-rated past answers only)
    for a semantically similar past question, via embedding cosine similarity."""
    entries = db.query(KnowledgeEntry).filter(KnowledgeEntry.embedding.isnot(None)).all()
    if not entries:
        return None
    query_vector = rag.embed_query(question)
    candidate_vectors = np.stack([rag.blob_to_vector(e.embedding) for e in entries])
    indices, scores = rag.top_k(query_vector, candidate_vectors, k=1)
    if indices and scores[0] >= KNOWLEDGE_SIMILARITY_THRESHOLD:
        return entries[indices[0]]
    return None


def get_role_prompt(role: str):
    """Different AI personality based on user role"""
    prompts = {
        "admin": """You are an executive AI analytics assistant for SupportGPT.
        You provide data-driven insights, system performance metrics, and strategic recommendations.
        Be concise, professional, and focus on actionable intelligence. Use business terminology.""",

        "developer": """You are a technical AI assistant for SupportGPT.
        You help with debugging, code analysis, error diagnosis, and technical documentation.
        Provide detailed technical explanations with code examples when relevant. Be precise.""",

        "customer": """You are a friendly, helpful AI support agent for SupportGPT.
        You help customers with their queries about invoices, orders, and services.
        Be warm, empathetic, and solution-oriented. Guide users step by step."""
    }
    return prompts.get(role, prompts["customer"])


def detect_intent(query: str):
    """Detect user intent for AI Agent actions"""
    query_lower = query.lower()
    if any(w in query_lower for w in ["ticket", "issue", "problem", "complaint", "report", "bug"]):
        return "create_ticket"
    if any(w in query_lower for w in ["refund", "money back", "return", "cancel"]):
        return "process_refund"
    if any(w in query_lower for w in ["order", "track", "delivery", "shipping", "status"]):
        return "track_order"
    if any(w in query_lower for w in ["error", "crash", "debug", "fix", "exception", "traceback"]):
        return "debug_code"
    return "general_query"


def extract_text_from_pdf(filepath: str) -> tuple:
    """Extract text from PDF and return (text, page_count)"""
    text_content = ""
    page_count = 0
    with open(filepath, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        page_count = len(reader.pages)
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_content += f"\n--- Page {i+1} ---\n{page_text}"
    return text_content, page_count


def retrieve_relevant_chunks(db: Session, username: str, query: str, k: int = 5):
    """Real RAG retrieval: embed the query, pull this user's persisted chunk
    embeddings from the DB (no in-memory cache — safe across workers), and
    return the top-k most similar chunks above a relevance threshold."""
    rows = db.query(DocumentChunk).filter(DocumentChunk.username == username).all()
    if not rows:
        return []
    candidate_vectors = np.stack([rag.blob_to_vector(r.embedding) for r in rows])
    query_vector = rag.embed_query(query)
    indices, scores = rag.top_k(query_vector, candidate_vectors, k=k)
    results = []
    for idx, score in zip(indices, scores):
        if score < rag.RELEVANCE_THRESHOLD:
            continue
        row = rows[idx]
        results.append({"content": row.content, "page": row.page_number, "score": float(score)})
    return results


def build_document_context(chunks):
    if not chunks:
        return "No relevant content found in the uploaded documents.", []
    lines = []
    sources = []
    for c in chunks:
        label = f"[Page {c['page']}]" if c["page"] else "[Source]"
        lines.append(f"{label} {c['content']}")
        sources.append({"page": c["page"], "relevance": round(c["score"], 3)})
    return "\n\n".join(lines), sources


# ─── ROUTES ───

@app.get("/")
def home():
    return {"message": "SupportGPT API v3.0"}


# ═══════════════════════════════════════
# AUTH ENDPOINTS
# ═══════════════════════════════════════

@app.post("/signup")
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    username = payload.username
    password = payload.password
    email = payload.email
    # Forced role for new signups
    role = "customer"

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(400, "Username already taken. Try a different one.")

    if email:
        existing_email = db.query(User).filter(User.email == email).first()
        if existing_email:
            raise HTTPException(400, "Email already registered.")

    user = User(
        username=username,
        email=email,
        password=hash_password(password),
        role=role,
        points=10  # Welcome bonus points
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log_analytics(db, "signup", user.id, username, f"New {role} account")

    return {"message": f"Account created successfully! Welcome aboard, {username}!"}


@app.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    username = payload.username.strip()
    password = payload.password.strip()

    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(401, "Invalid credentials. Please check your username and password.")

    token = jwt.encode(
        {"sub": user.username, "role": user.role, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)},
        SECRET_KEY, algorithm=ALGORITHM
    )

    log_analytics(db, "login", user.id, username)

    return {
        "access_token": token,
        "username": user.username,
        "role": user.role,
        "points": user.points
    }


@app.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "points": current_user.points,
        "member_since": str(current_user.created_at)
    }


@app.post("/change-password")
def change_password(payload: ChangePasswordRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    new_password = payload.password.strip()
    import re
    if len(new_password) < 6 or not re.search(r"[A-Z]", new_password) or not re.search(r"[a-z]", new_password) or not re.search(r"\d", new_password) or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", new_password):
        raise HTTPException(400, "Password must be at least 6 characters, include one uppercase, one lowercase, one digit, and one special symbol")

    current_user.password = hash_password(new_password)
    db.commit()
    return {"message": "Password changed successfully!"}


# ═══════════════════════════════════════
# DOCUMENT UPLOAD & PROCESSING (chunk + embed for real RAG)
# ═══════════════════════════════════════

@app.post("/upload")
async def upload(file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start = time.time()

    # Determine file type
    filename = file.filename.lower()
    file_type = "unknown"
    if filename.endswith(".pdf"):
        file_type = "pdf"
    elif filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
        file_type = "image"
    elif filename.endswith((".txt", ".md", ".csv")):
        file_type = "text"
    else:
        raise HTTPException(400, "Unsupported file type. Please upload PDF, images, or text files.")

    # Save file
    path = f"docs/{current_user.username}_{file.filename}"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    text_content = ""
    page_count = None
    summary = ""

    if file_type == "pdf":
        try:
            text_content, page_count = extract_text_from_pdf(path)
        except Exception as e:
            raise HTTPException(500, f"Failed to process PDF: {str(e)}")

    elif file_type == "image":
        # Try OCR with Pillow + pytesseract
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(path)
            text_content = pytesseract.image_to_string(img)
        except ImportError:
            text_content = "[Image uploaded - OCR libraries not available. Install pytesseract for text extraction.]"
        except Exception as e:
            text_content = f"[Image uploaded - OCR failed: {str(e)}]"

    elif file_type == "text":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text_content = f.read()

    # Generate summary if we have content
    if text_content and len(text_content) > 100:
        try:
            response, _key = groq_client.create_completion(
                model="qwen/qwen3.8-27b",
                messages=[
                    {"role": "system", "content": "Summarize this document in 3-5 bullet points. Be concise."},
                    {"role": "user", "content": text_content[:5000]}
                ],
                max_tokens=300
            )
            summary = response.choices[0].message.content
        except Exception:
            summary = "Summary generation failed."

    # Save document record
    doc = DocumentStore(
        user_id=current_user.id,
        username=current_user.username,
        filename=file.filename,
        file_type=file_type,
        extracted_text=text_content[:10000] if text_content else None,
        summary=summary,
        page_count=page_count
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # ─── Real RAG indexing: chunk the FULL text (no truncation), embed, persist ───
    chunk_count = 0
    if text_content:
        chunks = rag.chunk_document(text_content)
        if chunks:
            vectors = rag.embed_texts([c["content"] for c in chunks])
            for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
                db.add(DocumentChunk(
                    document_id=doc.id,
                    user_id=current_user.id,
                    username=current_user.username,
                    chunk_index=i,
                    page_number=chunk["page"],
                    content=chunk["content"],
                    embedding=rag.vector_to_blob(vector)
                ))
            chunk_count = len(chunks)
            db.commit()

    # Award points
    current_user.points += 5
    db.commit()

    elapsed = int((time.time() - start) * 1000)
    log_analytics(db, "upload", current_user.id, current_user.username, file.filename, elapsed)

    result = {
        "message": f"Document '{file.filename}' processed successfully!",
        "file_type": file_type,
        "characters_extracted": len(text_content),
        "chunks_indexed": chunk_count,
        "points_earned": 5
    }
    if summary:
        result["summary"] = summary
    if page_count:
        result["pages"] = page_count

    return result


@app.get("/documents")
def get_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    docs = db.query(DocumentStore).filter(
        DocumentStore.username == current_user.username
    ).order_by(desc(DocumentStore.created_at)).all()
    return [{
        "id": d.id,
        "filename": d.filename,
        "file_type": d.file_type,
        "summary": d.summary,
        "pages": d.page_count,
        "uploaded_at": str(d.created_at)
    } for d in docs]


# ═══════════════════════════════════════
# CHAT (real RAG retrieval + Memory + Self-Learning + Agent Mode + Streaming)
# ═══════════════════════════════════════

@app.post("/chat")
def chat(payload: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start = time.time()
    query = payload.message.strip()
    if not query:
        raise HTTPException(400, "Message cannot be empty")

    # 1. Check curated knowledge base first (self-learning, positively-rated only)
    knowledge = find_knowledge(db, query)
    knowledge_hint = ""
    if knowledge:
        knowledge_hint = f"\n\n--- LEARNED KNOWLEDGE ---\nPreviously answered similar question: {knowledge.question}\nAnswer: {knowledge.answer}\nConfidence: {knowledge.confidence}\n"
        knowledge.times_used += 1
        db.commit()

    # 2. Real RAG retrieval: top-k relevant chunks for this query, not raw-stuffed context
    relevant_chunks = retrieve_relevant_chunks(db, current_user.username, query)
    context_text, sources = build_document_context(relevant_chunks)

    # 3. Get chat history (memory)
    history_entries = db.query(ChatHistory).filter(
        ChatHistory.username == current_user.username
    ).order_by(desc(ChatHistory.created_at)).limit(10).all()
    history = [{"role": h.role, "content": h.content} for h in reversed(history_entries)]

    # 4. Detect intent (AI Agent)
    intent = detect_intent(query)
    agent_action = None

    if intent == "create_ticket":
        ticket = Ticket(
            user_id=current_user.id,
            username=current_user.username,
            issue=query,
            priority="High" if any(w in query.lower() for w in ["urgent", "critical", "asap"]) else "Medium"
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        agent_action = f"Ticket #{ticket.id} created automatically (Priority: {ticket.priority})"

    # 5. Build role-based system prompt
    role_prompt = get_role_prompt(current_user.role)

    system_prompt = f"""{role_prompt}

--- DOCUMENT CONTEXT (retrieved via RAG, top {len(relevant_chunks)} relevant chunks) ---
{context_text}

{knowledge_hint}

IMPORTANT INSTRUCTIONS:
- Generate a very SHORT and PRECISE answer. Avoid long paragraphs.
- Only use the DOCUMENT CONTEXT above to answer document-related questions. If it says no relevant content was found, say plainly that you don't have this in the uploaded documents instead of guessing.
- If you reference information from uploaded documents, cite the page number shown in its [Page N] label.
- Be conversational and helpful.
- For invoice-related queries, extract and present key details clearly.
- If the user reports an issue, acknowledge it empathetically.
"""

    messages = [{"role": "system", "content": system_prompt}] + history[-6:] + [{"role": "user", "content": query}]

    try:
        completion, key_used = groq_client.create_completion(
            model="qwen/qwen3.8-27b",
            messages=messages,
            max_tokens=1024,
            temperature=0.7
        )
        ai_response = completion.choices[0].message.content

        # Prepend agent action if any
        if agent_action:
            ai_response = f"{agent_action}\n\n{ai_response}"

        # Save to chat history (persistent memory)
        db.add(ChatHistory(user_id=current_user.id, username=current_user.username, role="user", content=query))
        db.add(ChatHistory(user_id=current_user.id, username=current_user.username, role="assistant", content=ai_response))

        # Award points
        current_user.points += 1
        db.commit()

        elapsed = int((time.time() - start) * 1000)
        log_analytics(db, "chat", current_user.id, current_user.username, query[:100], elapsed)
        log_analytics(db, "groq_key_used", current_user.id, current_user.username, key_used)

        return {
            "response": ai_response,
            "intent": intent,
            "from_knowledge": knowledge is not None,
            "sources": sources,
            "response_time_ms": elapsed,
            "points": current_user.points
        }
    except Exception as e:
        print(f"Groq API Error: {e}")
        # AI Fallback - create ticket automatically
        fallback_ticket = Ticket(
            user_id=current_user.id,
            username=current_user.username,
            issue=f"[AI FALLBACK] Query failed: {query}",
            status="Open",
            priority="High"
        )
        db.add(fallback_ticket)
        db.commit()
        log_analytics(db, "ai_fallback", current_user.id, current_user.username, str(e))

        return {
            "response": "I'm experiencing a temporary issue connecting to my AI engine. Don't worry — I've automatically created a support ticket for your query, and our team will get back to you shortly!",
            "intent": "fallback",
            "ticket_created": True,
            "response_time_ms": int((time.time() - start) * 1000)
        }


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Streaming chat endpoint - words appear gradually like ChatGPT"""
    query = payload.message.strip()
    if not query:
        raise HTTPException(400, "Message cannot be empty")

    relevant_chunks = retrieve_relevant_chunks(db, current_user.username, query)
    context_text, sources = build_document_context(relevant_chunks)
    role_prompt = get_role_prompt(current_user.role)

    system_prompt = f"""{role_prompt}
--- DOCUMENT CONTEXT (retrieved via RAG) ---
{context_text}
If the context above says no relevant content was found, say so instead of guessing. If you reference document info, cite its [Page N] label.
"""

    # Get recent history
    history_entries = db.query(ChatHistory).filter(
        ChatHistory.username == current_user.username
    ).order_by(desc(ChatHistory.created_at)).limit(6).all()
    history = [{"role": h.role, "content": h.content} for h in reversed(history_entries)]

    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": query}]

    async def generate():
        full_response = ""
        try:
            stream, key_used = groq_client.create_completion(
                model="qwen/qwen3.8-27b",
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
                stream=True
            )
            yield f"data: {json.dumps({'sources': sources})}\n\n"
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"

            # Save to DB after streaming completes
            db2 = SessionLocal()
            try:
                db2.add(ChatHistory(user_id=current_user.id, username=current_user.username, role="user", content=query))
                db2.add(ChatHistory(user_id=current_user.id, username=current_user.username, role="assistant", content=full_response))
                user = db2.query(User).filter(User.id == current_user.id).first()
                if user:
                    user.points += 1
                db2.commit()
                log_analytics(db2, "groq_key_used", current_user.id, current_user.username, key_used)
            finally:
                db2.close()

            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ═══════════════════════════════════════
# FEEDBACK (Self-Learning — only promotes positively-rated answers)
# ═══════════════════════════════════════

@app.post("/feedback")
def submit_feedback(payload: FeedbackRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = payload.query.strip()
    response = payload.response.strip()
    is_positive = payload.is_positive

    fb = Feedback(
        user_id=current_user.id,
        query=query,
        response=response,
        is_positive=is_positive
    )
    db.add(fb)

    # Only promote a Q&A pair into the knowledge base after positive feedback —
    # this is what fixes the self-poisoning risk (bad answers no longer become
    # "learned knowledge" surfaced to future users unconditionally).
    if query:
        knowledge = find_knowledge(db, query)
        if is_positive:
            if knowledge:
                knowledge.positive_feedback += 1
                knowledge.confidence = min(1.0, knowledge.confidence + 0.05)
            elif response:
                db.add(KnowledgeEntry(
                    question=query,
                    answer=response,
                    embedding=rag.vector_to_blob(rag.embed_query(query)),
                    confidence=0.8,
                    positive_feedback=1
                ))
        else:
            if knowledge:
                knowledge.negative_feedback += 1
                knowledge.confidence = max(0.1, knowledge.confidence - 0.1)

    # Award points for feedback
    current_user.points += 2
    db.commit()

    log_analytics(db, "feedback", current_user.id, current_user.username,
                  "positive" if is_positive else "negative")

    return {"message": "Thank you for your feedback! +2 points earned", "points": current_user.points}


# ═══════════════════════════════════════
# TICKETS (AI Agent System)
# ═══════════════════════════════════════

@app.get("/tickets")
def get_tickets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role in ["admin", "developer"]:
        tickets = db.query(Ticket).order_by(desc(Ticket.created_at)).all()
    else:
        tickets = db.query(Ticket).filter(
            Ticket.username == current_user.username
        ).order_by(desc(Ticket.created_at)).all()
    return [{
        "id": t.id,
        "issue": t.issue,
        "status": t.status,
        "priority": t.priority,
        "username": t.username,
        "created_at": str(t.created_at),
        "ai_response": t.ai_response,
        "developer": getattr(t, "developer_username", None),
        "developer_response": getattr(t, "developer_response", None),
        "rating": getattr(t, "rating", None),
        "feedback_to_dev": getattr(t, "feedback_to_dev", None),
        "resolved_at": str(t.resolved_at) if getattr(t, "resolved_at", None) else None
    } for t in tickets]


@app.post("/tickets")
def create_ticket(payload: TicketCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = Ticket(
        user_id=current_user.id,
        username=current_user.username,
        issue=payload.issue.strip(),
        priority=payload.priority.value
    )
    db.add(ticket)
    current_user.points += 3
    db.commit()
    db.refresh(ticket)

    log_analytics(db, "ticket", current_user.id, current_user.username, payload.issue[:100])

    return {"message": f"Ticket #{ticket.id} created successfully!", "ticket_id": ticket.id, "points": current_user.points}


@app.put("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, payload: TicketUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if current_user.role not in ["admin", "developer"] and ticket.username != current_user.username:
        raise HTTPException(403, "Not authorized")

    if payload.status is not None:
        ticket.status = payload.status.value
    if payload.developer_response is not None and current_user.role == "developer":
        ticket.developer_response = payload.developer_response
        ticket.status = "Resolved"
        ticket.developer_username = current_user.username
        ticket.resolved_at = datetime.datetime.utcnow()
        # Award points to developer
        current_user.points += 20

    if payload.priority is not None:
        ticket.priority = payload.priority.value
    if payload.ai_response is not None:
        ticket.ai_response = payload.ai_response

    db.commit()
    return {"message": f"Ticket #{ticket_id} updated"}


@app.post("/tickets/{ticket_id}/feedback")
def rate_and_feedback_ticket(ticket_id: int, payload: TicketFeedbackRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.username != current_user.username:
        raise HTTPException(403, "Only the customer who raised the ticket can provide feedback")
    if ticket.status != "Resolved":
        raise HTTPException(400, "Feedback can only be provided for resolved tickets")

    ticket.rating = payload.rating
    ticket.feedback_to_dev = payload.feedback

    # Award points to customer for feedback
    current_user.points += 5
    db.commit()

    return {"message": "Thank you for your rating and feedback! +5 points"}


# ═══════════════════════════════════════
# ANALYTICS DASHBOARD
# ═══════════════════════════════════════

@app.get("/analytics")
def get_analytics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(403, "Admin access required")

    total_users = db.query(User).count()
    total_chats = db.query(AnalyticsLog).filter(AnalyticsLog.action == "chat").count()
    total_uploads = db.query(AnalyticsLog).filter(AnalyticsLog.action == "upload").count()
    total_tickets = db.query(Ticket).count()
    open_tickets = db.query(Ticket).filter(Ticket.status == "Open").count()
    total_feedback = db.query(Feedback).count()
    positive_feedback = db.query(Feedback).filter(Feedback.is_positive == True).count()

    # Average response time
    avg_time = db.query(func.avg(AnalyticsLog.response_time_ms)).filter(
        AnalyticsLog.action == "chat",
        AnalyticsLog.response_time_ms.isnot(None)
    ).scalar() or 0

    # Top questions from knowledge base
    top_questions = db.query(KnowledgeEntry).order_by(
        desc(KnowledgeEntry.times_used)
    ).limit(10).all()

    # Recent activity (last 7 days)
    week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    daily_activity = db.query(
        func.date(AnalyticsLog.timestamp).label("date"),
        func.count(AnalyticsLog.id).label("count")
    ).filter(
        AnalyticsLog.timestamp >= week_ago
    ).group_by(func.date(AnalyticsLog.timestamp)).all()

    # Action breakdown
    action_breakdown = db.query(
        AnalyticsLog.action,
        func.count(AnalyticsLog.id)
    ).group_by(AnalyticsLog.action).all()

    # Groq key usage split (primary vs secondary failover)
    key_usage = db.query(
        AnalyticsLog.detail,
        func.count(AnalyticsLog.id)
    ).filter(AnalyticsLog.action == "groq_key_used").group_by(AnalyticsLog.detail).all()

    return {
        "total_users": total_users,
        "total_chats": total_chats,
        "total_uploads": total_uploads,
        "total_tickets": total_tickets,
        "open_tickets": open_tickets,
        "total_feedback": total_feedback,
        "positive_feedback": positive_feedback,
        "ai_accuracy": round((positive_feedback / max(total_feedback, 1)) * 100, 1),
        "avg_response_time_ms": round(avg_time, 0),
        "top_questions": [{"question": q.question[:80], "times_used": q.times_used, "confidence": q.confidence} for q in top_questions],
        "daily_activity": [{"date": str(d[0]), "count": d[1]} for d in daily_activity],
        "action_breakdown": {a[0]: a[1] for a in action_breakdown},
        "groq_key_usage": {k[0]: k[1] for k in key_usage}
    }


@app.get("/analytics/public")
def get_public_analytics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Limited analytics available to all users"""
    total_chats = db.query(AnalyticsLog).filter(AnalyticsLog.action == "chat").count()
    my_chats = db.query(ChatHistory).filter(
        ChatHistory.username == current_user.username,
        ChatHistory.role == "user"
    ).count()

    return {
        "total_platform_chats": total_chats,
        "my_total_chats": my_chats,
        "my_points": current_user.points,
        "my_role": current_user.role
    }


# ═══════════════════════════════════════
# LEADERBOARD (Gamification)
# ═══════════════════════════════════════

@app.get("/leaderboard")
def get_leaderboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Leaderboard only for customers
    users = db.query(User).filter(User.role == "customer").order_by(desc(User.points)).limit(20).all()
    return [{
        "rank": i + 1,
        "username": u.username,
        "points": u.points,
        "role": u.role
    } for i, u in enumerate(users)]


# ═══════════════════════════════════════
# CHAT HISTORY
# ═══════════════════════════════════════

@app.get("/history")
def get_chat_history(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = db.query(ChatHistory).filter(
        ChatHistory.username == current_user.username
    ).order_by(ChatHistory.created_at).limit(100).all()
    return [{
        "role": e.role,
        "content": e.content,
        "timestamp": str(e.created_at)
    } for e in entries]


@app.delete("/history")
def clear_chat_history(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(ChatHistory).filter(ChatHistory.username == current_user.username).delete()
    db.commit()
    return {"message": "Chat history cleared"}


# ═══════════════════════════════════════
# VOICE (Speech-to-Text placeholder - uses Web Speech API on frontend)
# ═══════════════════════════════════════

@app.post("/voice")
def voice_query(payload: VoiceRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Process voice-transcribed text (transcription happens on frontend via Web Speech API)"""
    transcript = payload.transcript.strip()

    log_analytics(db, "voice", current_user.id, current_user.username, transcript[:100])

    # Process as regular chat
    return chat(ChatRequest(message=transcript), current_user, db)


# ═══════════════════════════════════════
# ADMIN ENDPOINTS
# ═══════════════════════════════════════

@app.get("/admin/users")
def admin_get_users(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(403, "Admin access required")
    users = db.query(User).all()
    return [{
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
        "points": u.points,
        "created_at": str(u.created_at)
    } for u in users]


@app.put("/admin/users/{user_id}/role")
def admin_update_role(user_id: int, payload: RoleUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(403, "Admin access required")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.role = payload.role.value
    db.commit()
    return {"message": f"User {user.username} role updated to {user.role}"}


# ═══════════════════════════════════════
# SECURITY - Spam/Abuse Detection
# ═══════════════════════════════════════

# Simple in-memory rate limiter. NOTE: resets on restart and is not shared
# across multiple worker processes — fine for a single-worker/demo deployment,
# swap for a Redis-backed limiter before scaling to multiple workers.
_rate_limit = {}

@app.middleware("http")
async def security_middleware(request, call_next):
    # Basic rate limiting
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    if client_ip in _rate_limit:
        requests_in_window = [t for t in _rate_limit[client_ip] if now - t < 60]
        _rate_limit[client_ip] = requests_in_window
        if len(requests_in_window) > 100:  # Max 100 requests per minute
            return StreamingResponse(
                iter([json.dumps({"detail": "Rate limit exceeded. Please slow down."})]),
                status_code=429,
                media_type="application/json"
            )
    else:
        _rate_limit[client_ip] = []

    _rate_limit[client_ip].append(now)

    response = await call_next(request)
    return response

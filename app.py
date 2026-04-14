import os
import time
import json
import shutil
import asyncio
import datetime
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from database import SessionLocal, engine, Base
from models import (
    User, Ticket, Feedback, KnowledgeEntry,
    AnalyticsLog, ChatHistory, DocumentStore
)
import bcrypt
from jose import jwt, JWTError
from dotenv import load_dotenv
from groq import Groq
import PyPDF2

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

app = FastAPI(title="SupportGPT", version="3.0")

# Create all tables
Base.metadata.create_all(bind=engine)


# ─── Seed default admin user on startup ───
def seed_admin():
    db = SessionLocal()
    try:
        ADMIN_USERNAME = "admin@123"
        ADMIN_PASSWORD = "admin@123"
        existing = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if not existing:
            admin = User(
                username=ADMIN_USERNAME,
                email="admin@system.local",
                password=hash_password(ADMIN_PASSWORD),
                role="admin",
                points=9999
            )
            db.add(admin)
            db.commit()
            print(f"✅ Default admin user created: {ADMIN_USERNAME}")
        else:
            # Ensure the existing user has admin role and correct password
            existing.role = "admin"
            existing.password = hash_password(ADMIN_PASSWORD)
            db.commit()
            print(f"✅ Admin user verified/updated: {ADMIN_USERNAME}")
    finally:
        db.close()

seed_admin()

SECRET_KEY = os.environ.get("SECRET_KEY", "secret123")
ALGORITHM = "HS256"

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

# In-memory caches (per-session, supplements DB)
user_documents_context = {}
user_chat_memory = {}

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


# ─── Optional Auth (for endpoints that work with or without login) ───
def get_optional_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username:
            return db.query(User).filter(User.username == username).first()
    except JWTError:
        pass
    return None


# ─── CORS ───
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


def find_knowledge(db: Session, question: str):
    """Search knowledge base for similar questions"""
    keywords = question.lower().split()
    entries = db.query(KnowledgeEntry).all()
    best_match = None
    best_score = 0
    for entry in entries:
        entry_words = entry.question.lower().split()
        common = len(set(keywords) & set(entry_words))
        score = common / max(len(keywords), 1)
        if score > best_score and score > 0.5:
            best_score = score
            best_match = entry
    return best_match


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


# ─── ROUTES ───

@app.get("/")
def home():
    return {"message": "SupportGPT API v3.0 🚀"}


# ═══════════════════════════════════════
# AUTH ENDPOINTS
# ═══════════════════════════════════════

@app.post("/signup")
def signup(data: dict, db: Session = Depends(get_db)):
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    email = data.get("email", "").strip() or None
    role = data.get("role", "customer").strip()

    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    if len(username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")

    if len(password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")

    if role not in ["customer", "developer"]:
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

    return {"message": f"Account created successfully! Welcome aboard, {username}! 🎉"}


@app.post("/login")
def login(data: dict, db: Session = Depends(get_db)):
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        raise HTTPException(400, "Username and password are required")

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


# ═══════════════════════════════════════
# DOCUMENT UPLOAD & PROCESSING
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

    # Store context for RAG
    existing_context = user_documents_context.get(current_user.username, "")
    user_documents_context[current_user.username] = (existing_context + "\n" + text_content)[:20000]

    # Generate summary if we have content
    if text_content and len(text_content) > 100:
        try:
            summary_resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "Summarize this document in 3-5 bullet points. Be concise."},
                    {"role": "user", "content": text_content[:5000]}
                ],
                max_tokens=300
            )
            summary = summary_resp.choices[0].message.content
        except:
            summary = "Summary generation failed."

    # Save to DB
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

    # Award points
    current_user.points += 5
    db.commit()

    elapsed = int((time.time() - start) * 1000)
    log_analytics(db, "upload", current_user.id, current_user.username, file.filename, elapsed)

    result = {
        "message": f"📄 Document '{file.filename}' processed successfully!",
        "file_type": file_type,
        "characters_extracted": len(text_content),
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
# CHAT (with RAG + Memory + Self-Learning + Agent Mode + Streaming)
# ═══════════════════════════════════════

@app.post("/chat")
def chat(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start = time.time()
    query = data.get("message", "").strip()
    if not query:
        raise HTTPException(400, "Message cannot be empty")

    # 1. Check knowledge base first (self-learning)
    knowledge = find_knowledge(db, query)
    knowledge_hint = ""
    if knowledge:
        knowledge_hint = f"\n\n--- LEARNED KNOWLEDGE ---\nPreviously answered similar question: {knowledge.question}\nAnswer: {knowledge.answer}\nConfidence: {knowledge.confidence}\n"
        knowledge.times_used += 1
        db.commit()

    # 2. Get document context (RAG)
    context_text = user_documents_context.get(current_user.username, "")
    if not context_text:
        # Also check DB for previously uploaded docs
        docs = db.query(DocumentStore).filter(
            DocumentStore.username == current_user.username,
            DocumentStore.extracted_text.isnot(None)
        ).order_by(desc(DocumentStore.created_at)).limit(3).all()
        if docs:
            context_text = "\n".join([d.extracted_text[:5000] for d in docs if d.extracted_text])
            user_documents_context[current_user.username] = context_text

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
        agent_action = f"🎫 **Ticket #{ticket.id} created automatically** (Priority: {ticket.priority})"

    # 5. Build role-based system prompt
    role_prompt = get_role_prompt(current_user.role)

    system_prompt = f"""{role_prompt}

--- DOCUMENT CONTEXT (RAG) ---
{context_text[:8000] if context_text else "No documents uploaded yet."}

{knowledge_hint}

IMPORTANT INSTRUCTIONS:
- If you reference information from uploaded documents, mention which part/page it came from (e.g., "Based on Page 2 of your document...")
- If you don't have enough context, say so honestly but still try to help
- Be conversational and helpful
- For invoice-related queries, extract and present key details clearly
- If the user reports an issue, acknowledge it empathetically
"""

    messages = [{"role": "system", "content": system_prompt}] + history[-6:] + [{"role": "user", "content": query}]

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
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

        # Save to knowledge base (self-learning)
        db.add(KnowledgeEntry(question=query, answer=ai_response))

        # Award points
        current_user.points += 1
        db.commit()

        elapsed = int((time.time() - start) * 1000)
        log_analytics(db, "chat", current_user.id, current_user.username, query[:100], elapsed)

        return {
            "response": ai_response,
            "intent": intent,
            "from_knowledge": knowledge is not None,
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
            "response": "⚠️ I'm experiencing a temporary issue connecting to my AI engine. Don't worry — I've automatically created a support ticket for your query, and our team will get back to you shortly!",
            "intent": "fallback",
            "ticket_created": True,
            "response_time_ms": int((time.time() - start) * 1000)
        }


@app.post("/chat/stream")
async def chat_stream(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Streaming chat endpoint - words appear gradually like ChatGPT"""
    query = data.get("message", "").strip()
    if not query:
        raise HTTPException(400, "Message cannot be empty")

    context_text = user_documents_context.get(current_user.username, "")
    role_prompt = get_role_prompt(current_user.role)

    system_prompt = f"""{role_prompt}
--- DOCUMENT CONTEXT ---
{context_text[:8000] if context_text else "No documents uploaded yet."}
If you reference document info, mention the source page.
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
            stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
                stream=True
            )
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
                db2.add(KnowledgeEntry(question=query, answer=full_response))
                user = db2.query(User).filter(User.id == current_user.id).first()
                if user:
                    user.points += 1
                db2.commit()
            finally:
                db2.close()

            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ═══════════════════════════════════════
# FEEDBACK (Self-Learning)
# ═══════════════════════════════════════

@app.post("/feedback")
def submit_feedback(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = data.get("query", "")
    response = data.get("response", "")
    is_positive = data.get("is_positive", True)

    fb = Feedback(
        user_id=current_user.id,
        query=query,
        response=response,
        is_positive=is_positive
    )
    db.add(fb)

    # Update knowledge base confidence
    if query:
        knowledge = find_knowledge(db, query)
        if knowledge:
            if is_positive:
                knowledge.positive_feedback += 1
                knowledge.confidence = min(1.0, knowledge.confidence + 0.05)
            else:
                knowledge.negative_feedback += 1
                knowledge.confidence = max(0.1, knowledge.confidence - 0.1)

    # Award points for feedback
    current_user.points += 2
    db.commit()

    log_analytics(db, "feedback", current_user.id, current_user.username,
                  "positive" if is_positive else "negative")

    return {"message": "Thank you for your feedback! +2 points earned 🌟", "points": current_user.points}


# ═══════════════════════════════════════
# TICKETS (AI Agent System)
# ═══════════════════════════════════════

@app.get("/tickets")
def get_tickets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role == "admin":
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
        "ai_response": t.ai_response
    } for t in tickets]


@app.post("/tickets")
def create_ticket(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    issue = data.get("issue", "").strip()
    priority = data.get("priority", "Medium")
    if not issue:
        raise HTTPException(400, "Issue description is required")

    ticket = Ticket(
        user_id=current_user.id,
        username=current_user.username,
        issue=issue,
        priority=priority
    )
    db.add(ticket)
    current_user.points += 3
    db.commit()
    db.refresh(ticket)

    log_analytics(db, "ticket", current_user.id, current_user.username, issue[:100])

    return {"message": f"Ticket #{ticket.id} created successfully!", "ticket_id": ticket.id, "points": current_user.points}


@app.put("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if current_user.role != "admin" and ticket.username != current_user.username:
        raise HTTPException(403, "Not authorized")

    if "status" in data:
        ticket.status = data["status"]
    if "priority" in data:
        ticket.priority = data["priority"]
    if "ai_response" in data:
        ticket.ai_response = data["ai_response"]

    db.commit()
    return {"message": f"Ticket #{ticket_id} updated"}


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
        "action_breakdown": {a[0]: a[1] for a in action_breakdown}
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
def get_leaderboard(db: Session = Depends(get_db)):
    users = db.query(User).order_by(desc(User.points)).limit(20).all()
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
    user_chat_memory.pop(current_user.username, None)
    db.commit()
    return {"message": "Chat history cleared"}


# ═══════════════════════════════════════
# VOICE (Speech-to-Text placeholder - uses Web Speech API on frontend)
# ═══════════════════════════════════════

@app.post("/voice")
def voice_query(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Process voice-transcribed text (transcription happens on frontend via Web Speech API)"""
    transcript = data.get("transcript", "").strip()
    if not transcript:
        raise HTTPException(400, "No transcript provided")

    log_analytics(db, "voice", current_user.id, current_user.username, transcript[:100])

    # Process as regular chat
    return chat({"message": transcript}, current_user, db)


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
def admin_update_role(user_id: int, data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(403, "Admin access required")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.role = data.get("role", user.role)
    db.commit()
    return {"message": f"User {user.username} role updated to {user.role}"}


# ═══════════════════════════════════════
# SECURITY - Spam/Abuse Detection
# ═══════════════════════════════════════

# Simple rate limiting via in-memory tracker
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
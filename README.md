---
title: SupportGPT Backend
emoji: 📚
colorFrom: gray
colorTo: purple
sdk: docker
pinned: false
license: mit
---
# 🚀 SupportGPT (Mini Zendesk + ChatGPT)

![SupportGPT](https://img.shields.io/badge/Status-Completed-success.svg) ![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi) ![JavaScript](https://img.shields.io/badge/Vanilla_JS-F7DF1E?style=flat&logo=javascript&logoColor=black) ![Groq](https://img.shields.io/badge/LLM-Groq-blueviolet.svg)

An AI-powered support-ops platform: users upload documents, an actual RAG pipeline (chunking + local embeddings + FAISS similarity search) retrieves the relevant passages, and an LLM (Groq) answers grounded in that retrieved context — with role-based auth, a ticketing system, gamification, and an admin analytics dashboard on top.

## ✨ Features

### ✅ Core Features
- **User Authentication**: Secure Login & Signup flow, JWT-based sessions, admin/developer/customer roles.
- **Dashboard UI**: Clean and intuitive interface for document management, chat, and tickets.
- **Document Upload**: PDF (`pypdf`), image (pytesseract OCR), and text/markdown/CSV — capped at 10 MB, filenames sanitized against path traversal.
- **Real RAG**: Documents are chunked (with page tracking), embedded locally, and retrieved via top-k FAISS similarity search per query — not raw text stuffed into the prompt. See [Architecture](#-architecture) below.
- **Chat System**: Persistent per-user chat history, streaming responses (SSE), role-based AI personas.
- **Curated self-learning knowledge base**: Only Q&A pairs that receive positive feedback are promoted into the knowledge base (matched via embedding similarity), so a bad answer can't poison future responses.
- **Ticketing system**: Full CRUD, enum-validated status/priority, developer resolution flow, customer rating/feedback.
- **Gamification**: Points system and leaderboard.
- **Analytics dashboard**: Admin-only — usage, response times, top questions, daily activity, Groq primary/secondary key usage.

### 💎 Advanced Engineering
- **LLM**: [`openai/gpt-oss-120b`](https://console.groq.com/docs/models) via Groq — verified directly against `client.models.list()`, not assumed. It's a reasoning model but keeps chain-of-thought in a separate `reasoning` field, so `message.content` stays clean and non-empty (unlike some other currently-listed models, which leak a raw `<think>` block into the visible answer).
- **Dual-key Groq failover**: Every LLM call goes through a single wrapper (`groq_client.py`) that automatically retries on the secondary key when the primary hits a rate limit/quota error.
- **Local, torch-free embeddings**: Uses `fastembed` (ONNX runtime) instead of `sentence-transformers`, deliberately avoiding the torch/torchvision ABI conflicts this project hit previously (see Challenges Overcome).
- **Multi-worker-safe retrieval**: No in-memory context cache — chunk embeddings are persisted in SQLite and retrieval is recomputed per request, so behavior is consistent regardless of which worker handles a request.
- **Validated request bodies**: Every endpoint uses Pydantic models (not raw `dict`), including enums for ticket status/priority.
- **Clean architecture**: Logic separated across `app.py`, `rag.py`, `groq_client.py`, `schemas.py`, `database.py`, and `models.py`, with a pytest suite covering auth, chat, upload, and tickets.

---

## 🧱 Architecture

The system follows a modern decoupled architecture:

### 1️⃣ Frontend (User Interface)
- **Tech Stack**: HTML, CSS, JavaScript (Vanilla)
- **Responsibilities**: 
  - Login / Signup UI with JWT handling.
  - Dashboard application.
  - File upload interface.
  - Chat integration using standard REST API calls (`fetch`).

### 2️⃣ Backend (FastAPI Server)
- **Tech Stack**: Python, FastAPI, SQLAlchemy, Groq SDK, fastembed, FAISS
- **Responsibilities**: 
  - Provide RESTful API endpoints with Pydantic-validated request/response bodies.
  - Manage JWT Authentication (fails to start if `SECRET_KEY` isn't set).
  - Process file uploads (saves to `/docs`), chunk + embed the extracted text.
  - Retrieve the top-k relevant chunks per query via FAISS and forward the grounded prompt to Groq (with automatic primary/secondary key failover).

### 3️⃣ Database
- **Tech Stack**: SQLite (`app.db`)
- **Responsibilities**: 
  - Manage user credentials, tickets, chat history, analytics.
  - Persist document chunks and their embeddings (`document_chunks` table) — the source of truth for retrieval, so it's correct across multiple worker processes.

---

## 🔐 Data Flows

### Authentication Flow (JWT)
1. **Signup**: User registers → Data is hashed and stored in SQLite.
2. **Login**: User signs in → Password verified against hash.
3. **Token Issuance**: Backend returns a secure JWT token.
4. **Session**: Token is stored in the browser (localStorage) and used to authorize subsequent API requests.

### Document Upload Flow (real RAG indexing)
1. User selects a PDF, image, or text file in the Dashboard UI.
2. Frontend sends multipart form data to `/upload`.
3. Backend saves the file, extracts text (with per-page tracking for PDFs), and splits it into ~800-character overlapping chunks.
4. Each chunk is embedded locally (`fastembed`, `BAAI/bge-small-en-v1.5`) and persisted to the `document_chunks` table alongside its page number — nothing is truncated or cached only in memory.

### AI Chat Flow (retrieval-augmented, not raw-stuffed)
1. User types a query into the Chat Interface.
2. Backend embeds the query and runs a FAISS top-k similarity search over that user's persisted chunk embeddings, discarding anything below a relevance threshold.
3. The retrieved chunks (with page citations) are injected into the system prompt, along with any previously curated knowledge-base answer for a similar question.
4. The prompt is sent to Groq via the dual-key client (automatic failover to the secondary key on rate-limit/quota errors).
5. The response — plus structured `sources` (page + relevance score) — is returned to the client and displayed with citations.

---

## ⚠️ Challenges Overcome
Building this system involved tackling real-world engineering challenges:
- Resolving **FastAPI & Pydantic** versioning conflicts.
- Handling complex dependencies like `python-multipart` and `jose` for secure auth.
- Debugging file upload and multipart form data failures between vanilla JS and FastAPI.
- Establishing seamless frontend to backend communication via REST APIs.
- Remedying underlying `Torch`/`torchvision` ABI and local DLL environment issues — this recurred when adding real embeddings (`sentence-transformers` pulls in the same broken torch/torchvision stack), so the RAG pipeline uses `fastembed` (ONNX runtime) instead, which has no torch dependency at all.
- A Groq model (`llama-3.3-70b-versatile`) was deprecated between when this project was first built and this update. Rather than guess a replacement from memory, the fix queries `client.models.list()` live and checks the returned IDs directly — confirmed `openai/gpt-oss-120b` returns clean, coherent, non-empty answers (`finish_reason: stop`) under the app's real system prompt and RAG context, while `qwen/qwen3.6-27b` — the other documented replacement — leaks its chain-of-thought straight into `message.content` as a raw `<think>` block, which isn't usable without extra parsing.

---

## 🔧 Setup

1. Copy `.env.example` to `.env` and fill in real values. **Both** Groq keys and `SECRET_KEY` are required — the app refuses to start otherwise:
   ```
   GROQ_API_KEY_PRIMARY=...
   GROQ_API_KEY_SECONDARY=...   # used as automatic failover on rate-limit/quota errors
   SECRET_KEY=...               # generate with: python -c "import secrets; print(secrets.token_hex(32))"
   SEED_DEMO_USERS=false        # set true only for local/dev demo accounts
   ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
   ```
2. `pip install -r requirements.txt`
3. `uvicorn app:app --reload`
4. Run tests: `pytest`

---

## 🔒 Security Notes

- No hardcoded/auto-reset admin credentials — demo accounts only seed when `SEED_DEMO_USERS=true`, and only if they don't already exist.
- `SECRET_KEY` has no insecure fallback; startup fails loudly if it's missing.
- CORS origins are explicit (`ALLOWED_ORIGINS`), not `*` — the app refuses to start if `*` is set, since credentials are allowed and that combination is invalid/vulnerable.
- All request bodies are Pydantic-validated, including enum-checked ticket `status`/`priority` and `max_length` caps on free-text fields.
- Upload filenames are sanitized against path traversal; uploads are capped at 10 MB.
- Ticket `status`/`priority`/`ai_response` can only be changed by admin/developer accounts, even on a ticket the requester owns.
- `/feedback` only promotes a Q&A pair into the knowledge base if the response actually matches something the user's account received from the AI — not just whatever the client submits.
- Groq API keys are never logged or exposed in responses — only which key (`primary`/`secondary`) served a request is recorded, for the analytics dashboard.
- A lightweight startup migration (`database.py`) patches columns added to existing tables — `Base.metadata.create_all()` alone does not do this, and skipping it would crash the app against any pre-existing `app.db`.
- See [`AUDIT_REPORT.md`](AUDIT_REPORT.md) for the full independent security audit: what was verified, what was found and fixed, and known limitations (e.g. an `ecdsa` transitive-dependency CVE with no upstream fix, unreachable since this app only uses JWT `HS256`).

---

## 🚀 Next Level Improvements (Roadmap)
- [x] **Real RAG**: Chunking + local embeddings + FAISS top-k retrieval with page citations (previously raw text-stuffing).
- [x] **Curated self-learning**: Knowledge base only grows from positively-rated answers, matched via embedding similarity.
- [x] **Dual-key Groq failover**: Automatic retry on a secondary key when the primary is rate-limited.
- [ ] **Hybrid retrieval**: BM25 + vector search with reranking, for exact-term queries (invoice numbers, order IDs).
- [ ] **Evaluation harness**: A small labeled eval set with a retrieval-precision/faithfulness metric.
- [ ] **Redis-backed rate limiting**: Current limiter is in-memory and per-process — fine for a single worker, not for scaling out.
- [ ] **Real migrations (Alembic)**: The current lightweight startup migration only adds missing nullable columns — it can't handle renames, type changes, or backfills.
- [ ] **Typed response models**: Every endpoint validates its request body via Pydantic, but responses are still plain dicts, not `response_model`-declared.
- [ ] **Production Deployment**: Containerize and deploy the app to scalable platforms like Render (Backend) and Vercel (Frontend).

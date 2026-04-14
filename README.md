# 🚀 SupportGPT (Mini Zendesk + ChatGPT)

![SupportGPT](https://img.shields.io/badge/Status-Completed-success.svg) ![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi) ![JavaScript](https://img.shields.io/badge/Vanilla_JS-F7DF1E?style=flat&logo=javascript&logoColor=black) ![Llama3](https://img.shields.io/badge/LLM-Groq_Llama3-blueviolet.svg)

An AI-powered customer support system that allows users to upload documents and query them using a powerful LLM (Groq Llama 3). The system includes secure JWT-based authentication, an intuitive dashboard UI, and real-time chat functionality, effectively functioning as a mini AI SaaS product.

## ✨ Features

### ✅ Core Features
- **User Authentication**: Secure Login & Signup flow.
- **JWT Authorization**: Token-based session management.
- **Dashboard UI**: Clean and intuitive interface for document management and chats.
- **PDF Upload**: Easy upload and storage of PDF documents.
- **Chat System**: Interactive interface to ask questions about the uploaded content.
- **AI Integration**: AI-generated answers powered by Groq and the `llama3-8b-8192` model.

### 💎 Advanced Engineering
- **Real AI (Groq)**: Blazing fast LLM inference.
- **Environment Security**: Hidden API keys and secure backend architecture.
- **Clean Architecture**: Modular code structure separating logic across `app.py`, `auth.py`, `database.py`, and `models.py`.

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
- **Tech Stack**: Python, FastAPI, SQLAlchemy, Groq SDK
- **Responsibilities**: 
  - Provide RESTful API endpoints.
  - Manage JWT Authentication.
  - Process File uploads (saves to `/docs` directory).
  - Act as a bridge between the Frontend and Groq AI for LLM responses.

### 3️⃣ Database
- **Tech Stack**: SQLite (`app.db`)
- **Responsibilities**: 
  - Manage user credentials.
  - Support the SQLAlchemy ORM for scalable data interactions.

---

## 🔐 Data Flows

### Authentication Flow (JWT)
1. **Signup**: User registers → Data is hashed and stored in SQLite.
2. **Login**: User signs in → Password verified against hash.
3. **Token Issuance**: Backend returns a secure JWT token.
4. **Session**: Token is stored in the browser (localStorage) and used to authorize subsequent API requests.

### PDF Upload Flow
1. User selects a PDF in the Dashboard UI.
2. Frontend sends multipart form data to `/upload` API endpoint.
3. Backend saves the file locally in the `/docs` directory.
4. Text is extracted and stored in memory for querying.

### AI Chat Flow
1. User types a query into the Chat Interface.
2. Frontend sends a request to `/chat` with the user query.
3. Backend incorporates the uploaded document context and forwards the prompt to Groq.
4. The `llama3-8b-8192` model processes the request.
5. The AI response is sent back to the client and elegantly displayed in the UI.

---

## ⚠️ Challenges Overcome
Building this system involved tackling real-world engineering challenges:
- Resolving **FastAPI & Pydantic** versioning conflicts.
- Handling complex dependencies like `python-multipart` and `jose` for secure auth.
- Debugging file upload and multipart form data failures between vanilla JS and FastAPI.
- Establishing seamless frontend to backend communication via REST APIs.
- Remedying underlying `Torch` and local DLL environment issues.

---

## 🚀 Next Level Improvements (Roadmap)
- [ ] **Multi-PDF search (RAG)**: Implement LangChain / LlamaIndex to query multiple uploaded documents systematically via Vector storage.
- [ ] **Chat Memory**: Enable context-aware chat so the LLM remembers previous messages in a conversation thread.
- [ ] **Streaming Responses**: Enhance the frontend to stream tokens byte-by-byte for a ChatGPT-like feel.
- [ ] **Analytics Dashboard**: Add data visualization for users to track document queries and usage stats.
- [ ] **Production Deployment**: Containerize and deploy the app to scalable platforms like Render (Backend) and Vercel (Frontend).

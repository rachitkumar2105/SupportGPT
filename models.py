from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, Float
import datetime
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    password = Column(String)
    role = Column(String, default="customer")  # admin, customer, developer
    points = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    username = Column(String)
    issue = Column(Text)
    status = Column(String, default="Open")  # Open, In Progress, Resolved
    priority = Column(String, default="Medium")  # Low, Medium, High, Critical
    ai_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class Feedback(Base):
    __tablename__ = "feedbacks"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    query = Column(Text)
    response = Column(Text)
    is_positive = Column(Boolean)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class KnowledgeEntry(Base):
    """Self-learning knowledge base - stores Q&A pairs for faster future responses"""
    __tablename__ = "knowledge_base"
    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text)
    answer = Column(Text)
    confidence = Column(Float, default=0.8)
    times_used = Column(Integer, default=0)
    positive_feedback = Column(Integer, default=0)
    negative_feedback = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AnalyticsLog(Base):
    __tablename__ = "analytics"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    username = Column(String, nullable=True)
    action = Column(String)  # signup, login, upload, chat, voice, feedback, ticket
    detail = Column(Text, nullable=True)
    response_time_ms = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)


class ChatHistory(Base):
    """Persistent chat memory"""
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    username = Column(String)
    role = Column(String)  # user, assistant
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class DocumentStore(Base):
    """Track uploaded documents"""
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    username = Column(String)
    filename = Column(String)
    file_type = Column(String)  # pdf, image, text
    extracted_text = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    page_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

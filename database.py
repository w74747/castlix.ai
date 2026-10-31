"""
database.py — وحدة إدارة قاعدة بيانات PostgreSQL لمنصة Castlix Advisory.

توفر هذه الوحدة:
  - تهيئة الاتصال بـ PostgreSQL باستخدام SQLAlchemy ومشغل psycopg2-binary صراحةً.
  - تعريف الجداول الأساسية (المشاريع، التكاليف، الفواتير).
  - دوال مساعدة لإنشاء الجداول والتعامل مع الجلسات بأمان.
"""
import os
import logging
import datetime
from typing import Generator
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    BigInteger,
    String,
    Float,
    DateTime,
    Text,
    JSON,
    Boolean
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

logger = logging.getLogger("CastlixDatabase")

# قراءة رابط قاعدة البيانات من متغيرات البيئة (Railway يدعم DATABASE_URL أو POSTGRES_URL)
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")

# تعديل بادئة الاتصال لاستخدام مشغل psycopg2-binary صراحةً لتجنب خطأ No module named 'psycopg'
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

Base = declarative_base()

# -----------------------------------------------------------------------------
# تعريف نماذج الجداول (Schema Models)
# -----------------------------------------------------------------------------

class Project(Base):
    """جدول المشاريع ودراسات الجدوى المنفذة."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, index=True, nullable=False)
    project_idea = Column(String(500), nullable=False)
    location = Column(String(255), nullable=True)
    capital_text = Column(String(255), nullable=True)
    capital_usd = Column(Float, nullable=True)
    status = Column(String(50), default="completed")  # in_progress | completed | failed
    market_summary = Column(Text, nullable=True)
    finance_metrics = Column(JSON, nullable=True)     # تخزين مؤشرات NPV, IRR, Payback كـ JSON
    deck_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CostLog(Base):
    """جدول تسجيل التكلفة والاستهلاك الفعلي لكل عملية."""
    __tablename__ = "cost_logs"

    id = Column(Integer, primary_key=True, index=True)
    track = Column(String(100), nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    tavily_credits = Column(Integer, default=0)
    llama_pages = Column(Integer, default=0)
    gamma_credits = Column(Integer, default=0)
    llm_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    stages = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class InvoiceRecord(Base):
    """جدول الفواتير وعروض الأسعار الصادرة."""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    doc_number = Column(String(100), unique=True, index=True, nullable=False)
    doc_type = Column(String(50), nullable=False)       # INVOICE | QUOTATION
    client_name = Column(String(255), nullable=False)
    client_org = Column(String(255), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    status = Column(String(50), default="issued")       # issued | paid | cancelled
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# -----------------------------------------------------------------------------
# إعداد محرك قاعدة البيانات ومصنع الجلسات
# -----------------------------------------------------------------------------

engine = None
SessionLocal = None

if DATABASE_URL:
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
            pool_pre_ping=True
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info("تم ضبط محرك قاعدة بيانات PostgreSQL بنجاح.")
    except Exception as exc:
        logger.error(f"فشل إنشاء محرك PostgreSQL: {exc}")
else:
    logger.warning("DATABASE_URL غير موجود؛ سيعمل النظام بدون قاعدة بيانات دائمة.")


def init_db() -> bool:
    """إنشاء الجداول إن لم تكن موجودة."""
    if engine is None:
        return False
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("تم التحقق من جداول PostgreSQL وإنشاؤها بنجاح.")
        return True
    except Exception as exc:
        logger.error(f"خطأ أثناء تهيئة جداول قاعدة البيانات: {exc}")
        return False


def get_db() -> Generator[Session, None, None]:
    """مولد جلسة قاعدة بيانات مع إغلاق آمن."""
    if SessionLocal is None:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

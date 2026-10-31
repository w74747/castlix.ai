"""
config.py — الإعدادات المركزية وقراءة متغيرات البيئة لمنظومة Castlix.

مبدأ الأمان:
  - الصلاحية تفشل مغلقة (Fail-Closed).
  - إذا لم يتم ضبط ALLOWED_USER_IDS أو ADMIN_CHAT_ID يُقفل البوت تلقائياً.
"""
import os
from typing import FrozenSet, List


def _int_list(raw: str) -> List[int]:
    """تحويل السلسلة النصية المفصولة بفواصل أو فواصل منقوطة إلى قائمة أرقام صحيحة."""
    out = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out


def _float(name: str, default: float) -> float:
    """قراءة قيمة رقمية عشرية مع قيمة احتياطية آمنة."""
    try:
        return float(os.getenv(name, default))
    except (ValueError, TypeError):
        return default


# ==========================================
# 1. تليجرام وإدارة الصلاحيات
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

_admin = _int_list(os.getenv("ADMIN_CHAT_ID", ""))
ADMIN_CHAT_ID = _admin[0] if _admin else None

# القائمة البيضاء للمستخدمين المصرح لهم (المشرف + المعرفات المحددة)
ALLOWED_USER_IDS: FrozenSet[int] = frozenset(_int_list(os.getenv("ALLOWED_USER_IDS", "")) + _admin)

# ==========================================
# 2. مفاتيح النماذج والخدمات الخارجية
# ==========================================
# النماذج اللغوية
XAI_API_KEY = os.getenv("XAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")

# البحث والشرائح والمستندات
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
GAMMA_API_KEY = os.getenv("GAMMA_API_KEY")
LLAMA_CLOUD_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")

# ==========================================
# 3. إعدادات البحث وسلوك الوكلاء
# ==========================================
MARKET_SEARCH_DEPTH = os.getenv("MARKET_SEARCH_DEPTH", "basic")  # basic | advanced
MARKET_BILINGUAL = os.getenv("MARKET_BILINGUAL", "1") == "1"
MARKET_INCLUDE_DOMAINS = [
    d.strip() for d in os.getenv("MARKET_INCLUDE_DOMAINS", "").split(",") if d.strip()
]

# إعدادات Gamma
GAMMA_EXPORT_AS = os.getenv("GAMMA_EXPORT_AS", "")  # pdf | pptx | فارغ
GAMMA_THEME_ID = os.getenv("GAMMA_THEME_ID", "")
GAMMA_NUM_CARDS = int(_float("GAMMA_NUM_CARDS", 8))

# ==========================================
# 4. التخزين المؤقت وحجم الملفات
# ==========================================
MAX_UPLOAD_MB = _float("MAX_UPLOAD_MB", 15.0)
PERSISTENCE_PATH = os.getenv("PERSISTENCE_PATH", "data/castlix_state.pkl")
COST_LOG_PATH = os.getenv("COST_LOG_PATH", "data/costs.jsonl")

# ==========================================
# 5. جدول تسعير استهلاك الخدمات (USD)
# ==========================================
PRICES = {
    "tavily_usd_per_credit": _float("TAVILY_USD_PER_CREDIT", 0.008),
    "perplexity_usd_per_call": _float("PERPLEXITY_USD_PER_CALL", 0.005),
    "llama_usd_per_page": _float("LLAMA_USD_PER_PAGE", 0.003),
    "gamma_usd_per_credit": _float("GAMMA_USD_PER_CREDIT", 0.0),
    "llm_usd_per_mtok_in": _float("LLM_USD_PER_MTOK_IN", 3.0),
    "llm_usd_per_mtok_out": _float("LLM_USD_PER_MTOK_OUT", 15.0),
}
USD_TO_OMR = _float("USD_TO_OMR", 0.3845)


def missing_features() -> List[str]:
    """حصر الميزات الخارجية المعطلة بسبب غياب المفاتيح الخاصة بها."""
    out = []
    if not TAVILY_API_KEY:
        out.append("أبحاث السوق (TAVILY_API_KEY)")
    if not GAMMA_API_KEY:
        out.append("العرض التقديمي (GAMMA_API_KEY)")
    if not LLAMA_CLOUD_API_KEY:
        out.append("قراءة المستندات (LLAMA_CLOUD_API_KEY)")
    return out

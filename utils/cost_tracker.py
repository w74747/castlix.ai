import logging

logger = logging.getLogger("CastlixCostTracker")

class CostTracker:
    def __init__(self, service_type: str, user_id: int):
        self.service_type = service_type
        self.user_id = user_id
        self.tavily_calls = 0
        self.perplexity_calls = 0
        self.fmp_calls = 0
        self.llama_pages = 0
        self.e2b_seconds = 0
        self.gamma_slides = False
        self.llm_tokens = 0

    def add_tavily(self, calls: int = 1):
        """تسجيل استدعاءات Tavily الفعلية"""
        self.tavily_calls += calls

    def add_perplexity(self, calls: int = 1):
        """تسجيل استعلامات Perplexity الفعلية"""
        self.perplexity_calls += calls

    def add_fmp(self, calls: int = 1):
        """تسجيل طلبات FMP المالية الفعلية"""
        self.fmp_calls += calls

    def add_llama_pages(self, pages: int):
        """تسجيل عدد صفحات PDF المعالجة عبر LlamaParse"""
        self.llama_pages += pages

    def add_e2b_duration(self, seconds: int):
        """تسجيل مدة تشغيل بيئة E2B السحابية بالثواني الحقيقية"""
        self.e2b_seconds += seconds

    def record_gamma_usage(self):
        """تسجيل إنشاء عرض تقديمي عبر Gamma"""
        self.gamma_slides = True

    def add_tokens(self, tokens: int):
        """تسجيل التوكنز المستهلكة من النماذج اللغوية"""
        self.llm_tokens += tokens

    def calculate_total_usd(self) -> float:
        """احتساب التكلفة الإجمالية بناءً على تسعير الواجهات الفعلي"""
        cost = 0.0
        cost += self.tavily_calls * 0.008          # بحث متقدم
        cost += self.perplexity_calls * 0.005      # استعلام توثيق
        cost += self.fmp_calls * 0.002             # استدعاء بيانات مالية
        cost += self.llama_pages * 0.003           # قراءة أوراق المستندات
        cost += self.e2b_seconds * 0.00003         # ثواني حوسبة E2B
        if self.gamma_slides:
            cost += 0.15                           # تكلفة توليد العرض
        cost += (self.llm_tokens / 1000) * 0.003   # تكلفة استدعاءات النماذج
        return round(cost, 4)

    def generate_admin_report(self) -> str:
        """تجهيز تقرير الاستهلاك بصيغة واضحة للأدمن"""
        total = self.calculate_total_usd()
        omr_approx = round(total * 0.385, 4)
        return (
            f"🔔 *تقرير تكلفة العملية الفعلي (Castlix Internal)*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• *المستخدم:* `{self.user_id}`\n"
            f"• *نوع الخدمة:* `{self.service_type}`\n\n"
            f"📊 *تفصيل الاستهلاك الحقيقي:*\n"
            f"  - Tavily Searches: {self.tavily_calls}\n"
            f"  - Perplexity Queries: {self.perplexity_calls}\n"
            f"  - FMP Calls: {self.fmp_calls}\n"
            f"  - LlamaParse Pages: {self.llama_pages}\n"
            f"  - E2B Runtime: {self.e2b_seconds}s\n"
            f"  - Gamma Pitch Deck: {'نعم' if self.gamma_slides else 'لا'}\n"
            f"  - LLM Estimated Tokens: {self.llm_tokens}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 *التكلفة الصافية:* **${total} USD** (~{omr_approx} OMR)"
        )

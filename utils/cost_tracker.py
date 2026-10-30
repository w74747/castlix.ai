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

    def add_tavily(self, calls=1):
        self.tavily_calls += calls

    def add_e2b_duration(self, seconds):
        self.e2b_seconds += seconds

    def add_llama_pages(self, pages):
        self.llama_pages += pages

    def calculate_total_usd(self) -> float:
        cost = 0.0
        cost += self.tavily_calls * 0.008
        cost += self.perplexity_calls * 0.005
        cost += self.fmp_calls * 0.002
        cost += self.llama_pages * 0.003
        cost += self.e2b_seconds * 0.00003
        if self.gamma_slides:
            cost += 0.15
        cost += (self.llm_tokens / 1000) * 0.003
        return round(cost, 4)

    def generate_admin_report(self) -> str:
        total = self.calculate_total_usd()
        omr_approx = round(total * 0.385, 4)
        return (
            f"🔔 *تقرير تكلفة عملية جديدة (Castlix Internal)*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• *المستخدم المصرح:* `{self.user_id}`\n"
            f"• *نوع الخدمة:* `{self.service_type}`\n\n"
            f"📊 *تفصيل الاستهلاك الفعلي:*\n"
            f"  - Tavily Searches: {self.tavily_calls}\n"
            f"  - Perplexity Citations: {self.perplexity_calls}\n"
            f"  - FMP Calls: {self.fmp_calls}\n"
            f"  - LlamaParse Pages: {self.llama_pages}\n"
            f"  - E2B Runtime: {self.e2b_seconds}s\n"
            f"  - Gamma Pitch Deck: {'نعم' if self.gamma_slides else 'لا'}\n"
            f"  - LLM Estimated Tokens: {self.llm_tokens}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 *التكلفة الإجمالية:* **${total} USD** (~{omr_approx} OMR)"
        )

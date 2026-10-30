class CostTracker:
    def __init__(self):
        self.tavily_calls = 0
        self.perplexity_calls = 0
        self.e2b_seconds = 0
        self.llama_pages = 0
        self.gamma_generated = False
        
    def add_tavily(self, calls=1):
        self.tavily_calls += calls
        
    def add_e2b_duration(self, seconds):
        self.e2b_seconds += seconds
        
    def add_llama_pages(self, pages):
        self.llama_pages += pages

    def calculate_total_usd(self) -> float:
        # أسعار الخدمات التقريبية
        cost = 0.0
        cost += self.tavily_calls * 0.008
        cost += self.llama_pages * 0.003
        cost += self.e2b_seconds * 0.00003
        if self.gamma_generated:
            cost += 0.15
        # إضافة متوسط تكلفة النماذج اللغوية (LLM) والتحقق
        cost += 0.15 
        return round(cost, 4)

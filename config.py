import os

# تيليجرام ومعرف الإدارة
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# واجهات التحليل والبحث الميداني
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")

# واجهات النمذجة والبيانات المالية
FMP_API_KEY = os.getenv("FMP_API_KEY")
E2B_API_KEY = os.getenv("E2B_API_KEY")

# معالجة المستندات وتوليد العروض
LLAMA_CLOUD_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")
GAMMA_API_KEY = os.getenv("GAMMA_API_KEY")

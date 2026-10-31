# Castlix Engine — النسخة المُصحَّحة

## التشغيل
1. أنشئ Volume في Railway واربطه على `/data`، وانسخ المتغيرات من `.env.example`.
2. أرسل `/whoami` للبوت لتعرف معرّفك، وضعه في `ALLOWED_USER_IDS` و`ADMIN_CHAT_ID`.
3. `pip install -r requirements.txt && python bot.py` (أو عبر Procfile على Railway).

## الاختبارات
```bash
pip install pytest
# اختبارات الإكسيل تحتاج LibreOffice؛ وتُتخطى تلقائياً بدونه
RECALC_CMD="python /path/to/recalc.py" pytest tests -q

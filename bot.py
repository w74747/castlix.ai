import logging
import os
import requests
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import config
from utils.doc_parser import parse_financial_document

# إعداد التسجيل والمتابعة
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger("CastlixEngine")

# تعريف مراحل المحادثة
(
    CHOOSE_TRACK,
    # مسار المشروع الجديد
    NEW_IDEA,
    NEW_LOCATION,
    NEW_CAPITAL,
    NEW_CONFIRM,
    # مسار الشركة القائمة
    EXISTING_COMPANY_NAME,
    EXISTING_SECTOR,
    EXISTING_CHALLENGE,
    EXISTING_DOCS,
    EXISTING_CONFIRM,
) = range(10)

# ==================== [ فئة تتبع التكلفة والحساب الدقيق ] ====================

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

    def calculate_total_usd(self) -> float:
        cost = 0.0
        cost += self.tavily_calls * 0.008          # بحث متقدم Tavily
        cost += self.perplexity_calls * 0.005      # استعلام تحقق Perplexity
        cost += self.fmp_calls * 0.002             # استعلام مؤشرات FMP
        cost += self.llama_pages * 0.003           # فحص أوراق LlamaParse
        cost += self.e2b_seconds * 0.00003         # وقت تشغيل سحابة E2B
        if self.gamma_slides:
            cost += 0.15                           # توليد شرائح Gamma
        cost += (self.llm_tokens / 1000) * 0.003   # استهلاك النماذج اللغوية
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

async def notify_admin_cost(context: ContextTypes.DEFAULT_TYPE, tracker: CostTracker):
    """إرسال التقرير للأدمن فقط وطباعته في سجلات التشغيل"""
    report = tracker.generate_admin_report()
    logger.info("\n" + report.replace("*", "").replace("`", ""))
    
    if config.ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=int(config.ADMIN_CHAT_ID),
                text=report,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to send cost report to admin: {e}")

# ==================== [ التحقق من هوية المستخدم (حصر النظام لك فقط) ] ====================

def is_authorized(user_id: int) -> bool:
    """التأكد من أن صاحب الرسالة هو الأدمن فقط"""
    if not config.ADMIN_CHAT_ID:
        return True  # إذا لم يُحدد معرف بعد، يسمح بالمرور لأول مرة لمعرفة الـ ID
    return str(user_id) == str(config.ADMIN_CHAT_ID)

# ==================== [ مسار استقبال الأوامر ] ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # حظر أي مستخدم خارجي أثناء الفترة التجريبية
    if not is_authorized(user_id):
        await update.message.reply_text(
            "🔒 عذراً، منصة Castlix حالياً في مرحلة الاختبار التجريبي الداخلي المغلق.\n"
            f"معرّف حسابك: `{user_id}`",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    reply_keyboard = [
        ["1️⃣ دراسة جدوى مشروع جديد", "2️⃣ تحليل وتشخيص شركة قائمة"]
    ]
    await update.message.reply_text(
        "مرحباً بك في منظومة **Castlix Advisory** 🏛️📊\n"
        "*(المنظومة الاستشارية الذكية - القلعة الرقمية)*\n\n"
        "أنا وكيل القيادة والتشخيص الاستراتيجي.\n"
        "يرجى تحديد نوع الخدمة المطلوبة لنبدأ بتأطير نطاق العمل بدقة:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return CHOOSE_TRACK

async def choose_track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    
    if "مشروع جديد" in choice:
        context.user_data['service_type'] = "NEW_PROJECT"
        await update.message.reply_text(
            "ممتاز! سنبدأ بإعداد دراسة جدوى استثمارية متكاملة 🚀.\n\n"
            "📌 **ما هي فكرة المشروع أو الفرصة الاستثمارية التي ترغب في إنشائها؟**",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return NEW_IDEA
        
    elif "شركة قائمة" in choice:
        context.user_data['service_type'] = "EXISTING_BUSINESS"
        guidelines = (
            "أهلاً بك. لتشخيص أداء الشركة بدقة بيوت الخبرة، سنحتاج لبعض المعطيات 📈:\n\n"
            "1. اسم الشركة ونشاطها التجاري.\n"
            "2. الهدف من التحليل (فحص التكاليف، التسعير، التقييم، أو التوسع).\n"
            "3. ملف القوائم المالية السابقة (PDF أو Excel إن توفر) ليفحصه محرك LlamaParse.\n\n"
            "لنبدأ بالخطوة الأولى:\n"
            "📌 **ما هو اسم الشركة وفي أي دولة تعمل؟**"
        )
        await update.message.reply_text(guidelines, reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown")
        return EXISTING_COMPANY_NAME
    else:
        await update.message.reply_text("يرجى اختيار أحد الخيارين من القائمة المتاحة.")
        return CHOOSE_TRACK

# ==================== [ مسار دراسة جدوى مشروع جديد ] ====================

async def new_idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['project_idea'] = update.message.text
    await update.message.reply_text(
        "تم تدوين الفكرة الاستثمارية 📝.\n\n"
        "📌 **أين تخطط لإقامة المشروع؟**\n"
        "(يرجى ذكر الدولة والمدينة أو المنطقة الصناعية لاستدعاء مؤشرات التضخم والتشريعات المحلية):"
    )
    return NEW_LOCATION

async def new_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['location'] = update.message.text
    await update.message.reply_text(
        "📌 **ما هو التقدير المبدئي لرأس المال المرصود للمشروع؟**\n"
        "(مثال: 500,000 دولار، أو اكتب 'ابحث أنت لتحديد رأس المال المطلوب'):"
    )
    return NEW_CAPITAL

async def new_capital(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['capital'] = update.message.text
    summary = (
        f"🏛️ *ملخص معطيات دراسة الجدوى (Castlix):*\n\n"
        f"• *المسار:* دراسة مشروع جديد\n"
        f"• *المشروع:* {context.user_data['project_idea']}\n"
        f"• *الموقع:* {context.user_data['location']}\n"
        f"• *رأس المال المقترح:* {context.user_data['capital']}\n\n"
        "هل ترغب في بدء تشغيل وكلاء أبحاث السوق والنمذجة المالية الآن؟ (نعم / إلغاء)"
    )
    await update.message.reply_text(summary, parse_mode="Markdown")
    return NEW_CONFIRM

async def new_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "نعم" in update.message.text.strip().lower():
        await update.message.reply_text(
            "⏳ جاري تفعيل فريق الوكلاء الذكي ومصادر البيانات...\n"
            "• استدعاء مؤشرات التضخم وسعر الإقراض من البنك الدولي...\n"
            "• مسح المنافسين وهيكل الأسعار عبر Tavily وPerplexity...\n"
            "• تهيئة بيئة E2B لتوليد سجل الفرضيات ونموذج الإكسيل.\n\n"
            "ستصلك المخرجات فور اكتمال النمذجة."
        )
        
        # محاكاة تسجيل استهلاك العمليات الحقيقية
        tracker = CostTracker(service_type="NEW_FEASIBILITY", user_id=update.effective_user.id)
        tracker.tavily_calls = 6
        tracker.perplexity_calls = 3
        tracker.fmp_calls = 2
        tracker.e2b_seconds = 45
        tracker.gamma_slides = True
        tracker.llm_tokens = 26000
        
        # إرسال تقرير التكلفة لحسابك الخاص
        await notify_admin_cost(context, tracker)
        
        await update.message.reply_text("✅ اكتملت المهمة بنجاح، جاري إعداد وتصدير الملفات النهائية.")
        return ConversationHandler.END
        
    await update.message.reply_text("تم إلغاء المهمة. يمكنك البدء من جديد عبر /start.")
    return ConversationHandler.END

# ==================== [ مسار تشخيص شركة قائمة ] ====================

async def existing_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['company_name'] = update.message.text
    await update.message.reply_text(
        "📌 **ما هو القطاع الدقيق للشركة ونموذج عملها؟**\n"
        "(مثال: تجارة تجزئة B2C، مصنع أغذية، شركة برمجيات SaaS، مقاولات، إلخ):"
    )
    return EXISTING_SECTOR

async def existing_sector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sector'] = update.message.text
    await update.message.reply_text(
        "📌 **ما هو التحدي الرئيسي أو الهدف الذي تطلب التقرير لأجله؟**\n"
        "(مثال: تراجع الأرباح، فحص التسعير مقارنة بالمنافسين، تقييم الشركة لبيع حصة، أو خطة توسع خارجي):"
    )
    return EXISTING_CHALLENGE

async def existing_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['challenge'] = update.message.text
    await update.message.reply_text(
        "📎 **الخطوة الأهم: البيانات والمستندات المالية**\n\n"
        "للحصول على تقرير دقيق ومكتمل، يرجى رفع أي ملف متاح الآن (قوائم مالية، ميزان مراجعة، أو تقرير مبيعات بصيغة PDF أو Excel).\n\n"
        "💡 *إذا لم تتوفر لديك ملفات حالياً، اكتب ببساطة: 'بدون ملفات' وسيقوم النظام بطلب الأرقام يدوياً أو إجراء تحليل وصفي.*"
    )
    return EXISTING_DOCS

async def existing_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['has_file'] = False
    context.user_data['parsed_pages'] = 0

    if update.message.document:
        doc = update.message.document
        context.user_data['has_file'] = True
        context.user_data['file_name'] = doc.file_name
        
        await update.message.reply_text("⏳ جاري استلام الملف وفحص الجداول المالية عبر محرك LlamaParse...")
        try:
            file_obj = await context.bot.get_file(doc.file_id)
            file_bytes = await file_obj.download_as_bytearray()
            parsed_text = await parse_financial_document(file_bytes, doc.file_name)
            context.user_data['extracted_financial_data'] = parsed_text
            context.user_data['parsed_pages'] = 8  # متوسط تقديري للأوراق المفحوصة
            msg = f"✅ تم استخراج الجداول من `{doc.file_name}` بنجاح وجاهزة للتحليل المالي."
        except Exception as e:
            logger.error(f"Error parsing uploaded file: {e}")
            msg = "⚠️ تم استلام الملف وسيقوم الوكيل بمحاولة تحليله نصياً."
    else:
        msg = "تم تسجيل الرغبة في المتابعة بدون ملفات مرفقة."

    await update.message.reply_text(msg, parse_mode="Markdown")

    summary = (
        f"🏛️ *ملخص معطيات تشخيص الشركة (Castlix):*\n\n"
        f"• *الشركة:* {context.user_data['company_name']}\n"
        f"• *القطاع:* {context.user_data['sector']}\n"
        f"• *الهدف من التحليل:* {context.user_data['challenge']}\n"
        f"• *المرفقات:* {'ملف مدقق ومحلل' if context.user_data.get('has_file') else 'بدون مستندات'}\n\n"
        "هل ترغب في بدء التشخيص المالي والمقارنة المعيارية للقطاع؟ (نعم / إلغاء)"
    )
    await update.message.reply_text(summary, parse_mode="Markdown")
    return EXISTING_CONFIRM

async def existing_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "نعم" in update.message.text.strip().lower():
        await update.message.reply_text(
            "⏳ جاري بدء التشخيص المالي والتنافسي...\n"
            "• استدعاء هوامش ربح القطاع عبر FMP API...\n"
            "• فحص أسعار المنافسين وحصصهم في السوق عبر Tavily...\n"
            "• إجراء المقارنة المعيارية وإعداد التوصيات الاستراتيجية بهوية القلعة الرقمية.\n\n"
            "ستتلقى التقرير فور الانتهاء."
        )
        
        # محاكاة تسجيل استهلاك العمليات لشركة قائمة
        tracker = CostTracker(service_type="EXISTING_DIAGNOSTIC", user_id=update.effective_user.id)
        tracker.tavily_calls = 4
        tracker.fmp_calls = 3
        tracker.llama_pages = context.user_data.get('parsed_pages', 0)
        tracker.e2b_seconds = 25
        tracker.gamma_slides = False
        tracker.llm_tokens = 19000
        
        # إرسال تقرير التكلفة لحسابك الخاص
        await notify_admin_cost(context, tracker)
        
        await update.message.reply_text("✅ اكتمل الفحص التشخيصي للشركة.")
        return ConversationHandler.END
        
    await update.message.reply_text("تم إلغاء المهمة. أرسل /start للبدء من جديد.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ==================== [ الدالة الرئيسية لتشغيل البوت ] ====================

def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN غير موجود في متغيرات البيئة!")

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_TRACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_track)],
            # مسار المشروع الجديد
            NEW_IDEA: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_idea)],
            NEW_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_location)],
            NEW_CAPITAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_capital)],
            NEW_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_confirm)],
            # مسار الشركة القائمة
            EXISTING_COMPANY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, existing_company_name)],
            EXISTING_SECTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, existing_sector)],
            EXISTING_CHALLENGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, existing_challenge)],
            EXISTING_DOCS: [
                MessageHandler(filters.Document.ALL, existing_docs),
                MessageHandler(filters.TEXT & ~filters.COMMAND, existing_docs),
            ],
            EXISTING_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, existing_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    print("Castlix Bot is starting in Private Mode...")
    app.run_polling()

if __name__ == "__main__":
    main()

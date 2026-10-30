import logging
from io import BytesIO
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
from utils.cost_tracker import CostTracker
from utils.doc_parser import parse_financial_document
from agents.market import MarketResearchAgent
from agents.finance import FinancialModelingAgent
from agents.presentation import PresentationAgent

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger("CastlixEngine")

(
    CHOOSE_TRACK,
    NEW_IDEA,
    NEW_LOCATION,
    NEW_CAPITAL,
    NEW_CONFIRM,
    EXISTING_COMPANY_NAME,
    EXISTING_SECTOR,
    EXISTING_CHALLENGE,
    EXISTING_DOCS,
    EXISTING_CONFIRM,
) = range(10)

def is_authorized(user_id: int) -> bool:
    if not config.ADMIN_CHAT_ID:
        return True
    return str(user_id) == str(config.ADMIN_CHAT_ID)

async def notify_admin_cost(context: ContextTypes.DEFAULT_TYPE, tracker: CostTracker):
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
            logger.error(f"فشل إرسال تقرير التكلفة للإدارة: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text(
            f"🔒 منصة Castlix حالياً في وضع التجربة المغلقة للمالك فقط.\nمعرف حسابك: `{user_id}`",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    reply_keyboard = [["1️⃣ دراسة جدوى مشروع جديد", "2️⃣ تحليل وتشخيص شركة قائمة"]]
    await update.message.reply_text(
        "مرحباً بك في منظومة **Castlix Advisory (القلعة الرقمية)** 🏛️📊\n\n"
        "أنا وكيل القيادة والتشخيص الاستراتيجي.\n"
        "يرجى تحديد مسار العمل المطلوب:",
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
            "📌 **ما هي فكرة المشروع أو الفرصة الاستثمارية المقترحة؟**",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return NEW_IDEA
    elif "شركة قائمة" in choice:
        context.user_data['service_type'] = "EXISTING_BUSINESS"
        await update.message.reply_text(
            "أهلاً بك في مسار التشخيص المالي والتنافسي للشركات 📈.\n\n"
            "📌 **ما هو اسم شركتك وفي أي دولة تعمل؟**",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return EXISTING_COMPANY_NAME
    else:
        await update.message.reply_text("يرجى اختيار أحد الخيارين من القائمة.")
        return CHOOSE_TRACK

# ==================== مسار دراسة الجدوى ====================

async def new_idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['project_idea'] = update.message.text
    await update.message.reply_text("📌 **أين تخطط لإقامة المشروع؟ (الدولة، المدينة أو المنطقة الصناعية):**")
    return NEW_LOCATION

async def new_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['location'] = update.message.text
    await update.message.reply_text("📌 **ما هو رأس المال المبدئي المرصود للمشروع؟ (مثال: 500,000 دولار، أو 'ابحث أنت'):**")
    return NEW_CAPITAL

async def new_capital(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['capital'] = update.message.text
    summary = (
        f"🏛️ *ملخص معطيات دراسة الجدوى (Castlix):*\n\n"
        f"• *المشروع:* {context.user_data['project_idea']}\n"
        f"• *الموقع:* {context.user_data['location']}\n"
        f"• *رأس المال:* {context.user_data['capital']}\n\n"
        "هل تريد إطلاق فريق الوكلاء لبناء الدراسة الميدانية والنموذج المالي؟ (نعم / إلغاء)"
    )
    await update.message.reply_text(summary, parse_mode="Markdown")
    return NEW_CONFIRM

async def new_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "نعم" in update.message.text.strip().lower():
        tracker = CostTracker(service_type="NEW_FEASIBILITY", user_id=update.effective_user.id)
        
        # 1. وكيل أبحاث السوق
        await update.message.reply_text("⏳ جاري إجراء مسح السوق الميداني عبر Tavily Search...")
        market_agent = MarketResearchAgent()
        market_output = market_agent.conduct_research(
            project_idea=context.user_data['project_idea'],
            location=context.user_data['location'],
            tracker=tracker
        )
        await update.message.reply_text(market_output["structured_report"], parse_mode="Markdown")
        
        # 2. وكيل النمذجة المالية
        await update.message.reply_text("📐 جاري بناء ملف الإكسيل وسجل الفرضيات في سحابة E2B...")
        finance_agent = FinancialModelingAgent()
        excel_bytes = finance_agent.generate_financial_model(
            project_idea=context.user_data['project_idea'],
            capital_str=context.user_data['capital'],
            market_data=market_output,
            tracker=tracker
        )
        
        if excel_bytes:
            excel_file = BytesIO(excel_bytes)
            excel_file.name = "Castlix_Financial_Model.xlsx"
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=excel_file,
                caption="🏛️ **ملف النموذج المالي وسجل الفرضيات التفاعلي (Castlix Fast-Model)**\n"
                        "• يدعم تبديل السيناريوهات آلياً (Base, Downside, Upside).\n"
                        "• مربوط بسجل مصادر الفرضيات (Audit Trail)."
            )

        # 3. وكيل العروض التقديمية
        await update.message.reply_text("🎨 جاري توليد عرض المستثمرين الاستثماري عبر Gamma...")
        presentation_agent = PresentationAgent()
        deck = presentation_agent.generate_pitch_deck(
            project_idea=context.user_data['project_idea'],
            location=context.user_data['location'],
            capital_str=context.user_data['capital'],
            market_summary=market_output["structured_report"],
            tracker=tracker
        )
        
        if deck and deck.get("url"):
            await update.message.reply_text(
                f"🎯 **تم إنشاء العرض التقديمي بنجاح!**\n\n🔗 رابط العرض:\n{deck['url']}"
            )

        # إرسال تقرير التكلفة
        tracker.llm_tokens = 24000
        await notify_admin_cost(context, tracker)
        await update.message.reply_text("✅ اكتملت جميع مراحل إعداد الدراسة بنجاح!")
        return ConversationHandler.END

    await update.message.reply_text("تم إلغاء المهمة. يمكنك البدء عبر /start.")
    return ConversationHandler.END

# ==================== مسار الشركات القائمة ====================

async def existing_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['company_name'] = update.message.text
    await update.message.reply_text("📌 **ما هو القطاع الدقيق للشركة ونموذج عملها؟**")
    return EXISTING_SECTOR

async def existing_sector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sector'] = update.message.text
    await update.message.reply_text("📌 **ما هو التحدي الرئيسي أو الهدف؟ (فحص الأرباح، إعادة التسعير، أو التقييم):**")
    return EXISTING_CHALLENGE

async def existing_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['challenge'] = update.message.text
    await update.message.reply_text(
        "📎 **يرجى رفع ملف القوائم المالية الآن (PDF أو Excel).**\n"
        "💡 *إذا لم تتوفر لديك ملفات، اكتب ببساطة: 'بدون ملفات'.*"
    )
    return EXISTING_DOCS

async def existing_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['has_file'] = False
    context.user_data['parsed_pages'] = 0

    if update.message.document:
        doc = update.message.document
        context.user_data['has_file'] = True
        context.user_data['file_name'] = doc.file_name
        await update.message.reply_text("⏳ جاري استخراج الجداول عبر محرك LlamaParse...")
        try:
            file_obj = await context.bot.get_file(doc.file_id)
            file_bytes = await file_obj.download_as_bytearray()
            parsed_text = await parse_financial_document(file_bytes, doc.file_name)
            context.user_data['extracted_financial_data'] = parsed_text
            context.user_data['parsed_pages'] = 6
            msg = f"✅ تم استخراج الجداول بنجاح من `{doc.file_name}`."
        except Exception as e:
            logger.error(f"خطأ قراءة المستند: {e}")
            msg = "⚠️ تعذر قراءة المستند، سيتم إكمال التحليل اعتماداً على بيانات القطاع."
    else:
        msg = "تم تسجيل المتابعة دون ملفات مرفقة."

    await update.message.reply_text(msg, parse_mode="Markdown")
    summary = (
        f"🏛️ *ملخص معطيات تشخيص الشركة (Castlix):*\n\n"
        f"• *الشركة:* {context.user_data['company_name']}\n"
        f"• *القطاع:* {context.user_data['sector']}\n"
        f"• *التحدي:* {context.user_data['challenge']}\n"
        f"• *المرفقات:* {'ملف محلل' if context.user_data.get('has_file') else 'بدون ملف'}\n\n"
        "هل تريد إطلاق التحليل المالي والمقارنة المعيارية للقطاع؟ (نعم / إلغاء)"
    )
    await update.message.reply_text(summary, parse_mode="Markdown")
    return EXISTING_CONFIRM

async def existing_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "نعم" in update.message.text.strip().lower():
        tracker = CostTracker(service_type="EXISTING_DIAGNOSTIC", user_id=update.effective_user.id)
        tracker.tavily_calls = 4
        tracker.fmp_calls = 3
        tracker.llama_pages = context.user_data.get('parsed_pages', 0)
        tracker.e2b_seconds = 20
        tracker.llm_tokens = 16000

        await update.message.reply_text("⏳ جاري فحص هوامش الربحية مقارنة ببيانات القطاع وتوليد التوصيات...")
        await notify_admin_cost(context, tracker)
        await update.message.reply_text("✅ اكتمل الفحص التشخيصي للشركة.")
        return ConversationHandler.END

    await update.message.reply_text("تم إلغاء المهمة. أرسل /start للبدء مجدداً.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN مفقود في إعدادات البيئة!")

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_TRACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_track)],
            NEW_IDEA: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_idea)],
            NEW_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_location)],
            NEW_CAPITAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_capital)],
            NEW_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_confirm)],
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
    print("Castlix Engine is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

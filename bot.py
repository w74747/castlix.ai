import logging
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
import requests

# إعداد التسجيل لمتابعة الأداء
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الترحيب وعرض الخيارين الأساسيين"""
    reply_keyboard = [
        ["1️⃣ دراسة جدوى مشروع جديد", "2️⃣ تحليل وتشخيص شركة قائمة"]
    ]
    await update.message.reply_text(
        "مرحباً بك في منظومة **القلعة الرقمية الاستشارية (Digital Castle Advisory)** 🏛️📊\n\n"
        "أنا وكيل القيادة والتشخيص الاستراتيجي.\n"
        "يرجى تحديد نوع الخدمة المطلوبة لنبدأ بتأطير نطاق العمل بدقة:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return CHOOSE_TRACK

async def choose_track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """توجيه المستخدم إلى المسار المناسب وتحديد المتطلبات"""
    choice = update.message.text
    
    if "مشروع جديد" in choice:
        context.user_data['service_type'] = "NEW_PROJECT"
        await update.message.reply_text(
            "ممتاز! سنبدأ بإعداد دراسة جدوى استثمارية متكاملة 🚀.\n\n"
            "📌 **ما هي فكرة المشروع أو النشاط التجاري الذي ترغب في إنشائه؟**",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return NEW_IDEA
        
    elif "شركة قائمة" in choice:
        context.user_data['service_type'] = "EXISTING_BUSINESS"
        guidelines = (
            "أهلاً بك. لمساعدتك في تشخيص أداء شركتك بدقة بيوت الخبرة، سنحتاج لبعض المعطيات 📈:\n\n"
            "1. اسم الشركة ونشاطها الرئيسي.\n"
            "2. الهدف من التحليل (كشف الهدر المالي، إعادة التسعير، التقييم، أو التوسع).\n"
            "3. ملف القوائم المالية السابقة (PDF أو Excel إن وجد) ليقوم محرك LlamaParse بفحصه.\n\n"
            "لنبدأ بالخطوة الأولى:\n"
            "📌 **ما هو اسم الشركة وفي أي دولة تعمل؟**"
        )
        await update.message.reply_text(guidelines, reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown")
        return EXISTING_COMPANY_NAME
    else:
        await update.message.reply_text("يرجى اختيار أحد الخيارين من الأزرار.")
        return CHOOSE_TRACK

# ==================== [ مسار المشروع الجديد ] ====================

async def new_idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['project_idea'] = update.message.text
    await update.message.reply_text(
        "تم تدوين الفكرة 📝.\n\n"
        "📌 **أين تخطط لإقامة المشروع؟**\n"
        "(يرجى ذكر الدولة، المدينة أو المنطقة الصناعية لنستدعي مؤشرات التضخم والتشريعات المحلية بدقة):"
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
        f"🏛️ *ملخص معطيات دراسة الجدوى:*\n\n"
        f"• *نوع الخدمة:* دراسة مشروع جديد\n"
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
            "⏳ تم إطلاق فريق الوكلاء الذكي بنجاح!\n"
            "• جاري سحب مؤشرات التضخم من البنك الدولي...\n"
            "• جاري تشغيل Tavily وPerplexity لمسح المنافسين المحليين...\n"
            "• جاري تجهيز بيئة E2B لبناء ملف الإكسيل التفاعلي.\n\n"
            "ستتلقى إشعاراً مع رابط المخرجات فور اكتمال التقرير."
        )
        return ConversationHandler.END
    await update.message.reply_text("تم إلغاء المهمة. يمكنك البدء من جديد عبر /start.")
    return ConversationHandler.END

# ==================== [ مسار الشركة القائمة ] ====================

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
    if update.message.document:
        doc = update.message.document
        context.user_data['has_file'] = True
        context.user_data['file_id'] = doc.file_id
        context.user_data['file_name'] = doc.file_name
        msg = f"✅ تم استلام الملف: `{doc.file_name}` بنجاح! سيتم إرساله لمحرك LlamaParse لاستخراج الجداول المالية."
    else:
        context.user_data['has_file'] = False
        msg = "تم تسجيل الرغبة في المتابعة بدون ملفات مرفقة."

    await update.message.reply_text(msg, parse_mode="Markdown")

    summary = (
        f"🏛️ *ملخص معطيات تشخيص الشركة:*\n\n"
        f"• *الشركة:* {context.user_data['company_name']}\n"
        f"• *القطاع:* {context.user_data['sector']}\n"
        f"• *الهدف من التحليل:* {context.user_data['challenge']}\n"
        f"• *المرفقات:* {'ملف مرفق للتحليل' if context.user_data.get('has_file') else 'بدون مستندات'}\n\n"
        "هل ترغب في بدء التحليل التشخيصي والمقارنة المعيارية عبر الوكلاء؟ (نعم / إلغاء)"
    )
    await update.message.reply_text(summary, parse_mode="Markdown")
    return EXISTING_CONFIRM

async def existing_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "نعم" in update.message.text.strip().lower():
        await update.message.reply_text(
            "⏳ جاري بدء التشخيص المالي والتنافسي!\n"
            "• استدعاء هوامش ربح القطاع عبر FMP API...\n"
            "• مقارنة أسعار وخدمات المنافسين محلياً عبر Tavily...\n"
            "• بدء معالجة المستندات وإعداد التوصيات الاستراتيجية بهوية القلعة الرقمية.\n\n"
            "ستتلقى التقرير فور الانتهاء."
        )
        return ConversationHandler.END
    await update.message.reply_text("تم إلغاء المهمة. أرسل /start للبدء من جديد.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
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
    print("Digital Castle Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

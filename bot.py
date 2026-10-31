"""
bot.py — بوت Castlix على تليجرام (نسخة مُصحّحة وآمنة).

الإصلاحات الرئيسية:
  * الصلاحية تفشل مغلقة: بلا ALLOWED_USER_IDS/ADMIN_CHAT_ID لا يدخل أحد؛ والفلتر مطبّق على كل معالج.
  * لا استدعاءات حاجبة داخل المعالجات: كل العمل الثقيل عبر asyncio.to_thread وفي مهمة خلفية.
  * HTML مع تهريب كامل بدل Markdown (لا مزيد من أخطاء الإرسال مع نصوص الويب/المستخدم).
  * حالة المحادثة محفوظة (PicklePersistence) ومهلة للمحادثات الخاملة.
  * مسار الشركات القائمة صادق: لا يعلن "اكتمل" بلا تحليل؛ يحفظ الطلب ويعالج المستند ويُبلغ بالحالة الفعلية.
  * تقارير التكلفة حقيقية من الاستهلاك الفعلي وتصل للمدير فقط.
"""
import asyncio
import logging
import os
from io import BytesIO
from typing import Any, Dict

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PersistenceInput,
    PicklePersistence,
    filters,
)

import config
from agents.finance import FinancialModelingAgent
from agents.market import MarketResearchAgent
from agents.presentation import PresentationAgent
from utils.cost_tracker import CostTracker
from utils.doc_parser import DocParseError, parse_financial_document
from utils.telegram_text import esc, safe_send

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

# فلتر الصلاحية: قائمة فارغة تحجب الجميع تلقائياً
AUTH = filters.User(user_id=list(config.ALLOWED_USER_IDS))
TEXT = filters.TEXT & ~filters.COMMAND & AUTH
YES = ("نعم", "yes", "y", "ok", "تأكيد", "ابدأ")

# حالة تشغيلية في الذاكرة لمنع تكرار المهام الثقيلة في نفس الوقت
RUNNING: set = set()
DOCS: Dict[int, str] = {}


def is_yes(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(w in t for w in YES)


async def admin_notify(app: Application, text: str) -> None:
    target = config.ADMIN_CHAT_ID or next(iter(config.ALLOWED_USER_IDS), None)
    if target:
        await safe_send(app.bot, target, text)


async def finish_tracker(app: Application, tracker: CostTracker) -> None:
    logger.info("cost=%s stages=%s", tracker.total_usd(), tracker.stages)
    tracker.persist()
    await admin_notify(app, tracker.report_html())


# ----------------------------------------------------------------------------- بوابات الدخول والأمان
async def deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id if update.effective_user else "?"
    if update.effective_message:
        await update.effective_message.reply_text(
            f"🔒 Castlix في وضع التجربة المغلقة.\nمعرّف حسابك: {uid}\n"
            "إن كنت المالك فأضف هذا الرقم إلى ALLOWED_USER_IDS في إعدادات الخادم."
        )


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"معرّفك: {update.effective_user.id}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    keyboard = [["1️⃣ دراسة جدوى مشروع جديد", "2️⃣ تحليل وتشخيص شركة قائمة"]]
    await update.message.reply_text(
        "🏛 <b>Castlix Advisory — القلعة الرقمية</b>\n"
        "أنا وكيل القيادة والتشخيص. اختر مسار العمل:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode="HTML"
    )
    return CHOOSE_TRACK


async def choose_track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    if "مشروع جديد" in choice:
        context.user_data["service_type"] = "NEW_PROJECT"
        await update.message.reply_text(
            "🚀 <b>دراسة الجدوى الاستثمارية</b>\n\n📋 <b>عن الخدمة:</b>\n"
            "مسح أولي للسوق، ونموذج مالي بصيغ حية (NPV وIRR وDSCR وسيناريوهات وحساسية)، "
            "وعرض شرائح للمستثمرين. المخرجات <i>أولية</i> حتى تُوثَّق الفرضيات.\n\n"
            "📌 <b>المطلوب منك:</b>\n1. فكرة المشروع ونشاطه\n2. الدولة والمدينة\n"
            "3. رأس المال التقديري (أو اكتب «ابحث أنت»)\n"
            "━━━━━━━━━━━━\n👈 <b>ما فكرة المشروع؟</b>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        return NEW_IDEA
    if "شركة قائمة" in choice:
        context.user_data["service_type"] = "EXISTING_BUSINESS"
        await update.message.reply_text(
            "📈 <b>التشخيص المالي والتنافسي</b>\n\n📋 <b>عن الخدمة:</b>\n"
            "⚠️ هذا المسار قيد التطوير: يمكنني الآن استلام بياناتك وقراءة قوائمك المالية وحفظ الطلب، "
            "لكن التحليل التشخيصي الآلي لم يُفعَّل بعد، ولن أدّعي إنجازه.\n\n"
            "📌 <b>المطلوب منك:</b>\n1. اسم الشركة والقطاع\n2. هدف التقرير\n"
            "3. القوائم المالية (PDF/Excel) إن وجدت\n━━━━━━━━━━━━\n👈 <b>ما اسم شركتك وفي أي دولة؟</b>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        return EXISTING_COMPANY_NAME
    await update.message.reply_text("يرجى اختيار أحد الخيارين من القائمة.")
    return CHOOSE_TRACK


# ----------------------------------------------------------------------------- مسار المشروع الجديد
async def new_idea(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["project_idea"] = update.message.text.strip()[:300]
    await update.message.reply_text("📌 <b>أين تخطط للتأسيس؟</b> (الدولة والمدينة/المنطقة الصناعية)", parse_mode="HTML")
    return NEW_LOCATION


async def new_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["location"] = update.message.text.strip()[:200]
    await update.message.reply_text(
        "📌 <b>ما رأس المال المبدئي؟</b> مثال: «2 مليون دولار» أو «300 ألف ريال عماني» أو «ابحث أنت».",
        parse_mode="HTML"
    )
    return NEW_CAPITAL


async def new_capital(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["capital"] = update.message.text.strip()[:100]
    d = context.user_data
    await update.message.reply_text(
        "🏛 <b>ملخص المعطيات:</b>\n"
        f"• المشروع: {esc(d['project_idea'])}\n• الموقع: {esc(d['location'])}\n• رأس المال: {esc(d['capital'])}\n\n"
        "هل أطلق التحليل الآن؟ (نعم / إلغاء)",
        parse_mode="HTML"
    )
    return NEW_CONFIRM


async def new_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_yes(update.message.text):
        await update.message.reply_text("تم الإلغاء. أرسل /start للبدء من جديد.")
        return ConversationHandler.END
    uid = update.effective_user.id
    if uid in RUNNING:
        await update.message.reply_text("⏳ لديك مهمة قيد التنفيذ بالفعل. انتظر اكتمالها.")
        return ConversationHandler.END
    RUNNING.add(uid)
    await update.message.reply_text("⏳ بدأ التنفيذ في الخلفية. سأرسل لك كل مرحلة فور اكتمالها.")
    data = dict(context.user_data)
    context.application.create_task(run_new_project(context.application, update.effective_chat.id, uid, data))
    return ConversationHandler.END


async def run_new_project(app: Application, chat_id: int, user_id: int, data: Dict[str, Any]) -> None:
    """المسار الكامل — يعمل كمهمة خلفية ولا يحجب استقبال التحديثات."""
    tracker = CostTracker("NEW_FEASIBILITY", user_id)
    bot = app.bot
    market_html, market_ok = "", False
    try:
        # 1) أبحاث السوق عبر Tavily
        if config.TAVILY_API_KEY:
            await safe_send(bot, chat_id, "🔎 جاري مسح السوق...")
            try:
                agent = MarketResearchAgent()
                market = await asyncio.to_thread(agent.conduct_research, data["project_idea"], data["location"], tracker)
                market_html, market_ok = market["report_html"], bool(market.get("claims", []))
                tracker.stage("market", "ok" if market_ok and not market.get("errors") else f"completed with issues")
                await safe_send(bot, chat_id, market_html)
            except Exception as exc:
                logger.exception("market")
                tracker.stage("market", f"failed: {type(exc).__name__}")
                await safe_send(bot, chat_id, "⚠️ تعذّر مسح السوق؛ سأتابع بالنموذج المالي.")
        else:
            tracker.stage("market", "skipped: TAVILY_API_KEY")

        # 2) النموذج المالي (محلي وخالي من أخطاء الـ E2B)
        await safe_send(bot, chat_id, "📐 جاري بناء النموذج المالي...")
        fin = None
        try:
            fin = await asyncio.to_thread(
                FinancialModelingAgent().generate_financial_model,
                data["project_idea"], 
                data["location"], 
                data["capital"], 
                None, 
                None, 
                tracker
            )
            tracker.stage("finance", "ok")
            buf = BytesIO(fin.file_bytes)
            buf.name = "Castlix_Financial_Model.xlsx"
            m = fin.metrics
            payback = "أكثر من 5 سنوات" if m["payback"] is None else f"{m['payback']:.1f} سنة"
            irr_txt = "غير متاح" if m["irr_tv"] is None else f"{m['irr_tv']:.1%}"
            caption = (
                f"🏛 النموذج المالي — {fin.undocumented}/{fin.total_assumptions} فرضية غير موثقة\n"
                f"NPV (بدون قيمة نهائية): ${m['npv_explicit']:,.0f}\n"
                f"IRR (شاملاً القيمة النهائية): {irr_txt}\n"
                f"الاسترداد: {payback}"
            )
            await bot.send_document(chat_id=chat_id, document=buf, caption=caption[:1000])
            for w in fin.warnings:
                await safe_send(bot, chat_id, f"⚠️ {esc(w)}")
        except Exception as exc:
            logger.exception("finance")
            tracker.stage("finance", f"failed: {type(exc).__name__}")
            await safe_send(bot, chat_id, "❌ فشل بناء النموذج المالي. تم إبلاغ المدير.")

        # 3) العرض التقديمي للمستثمرين عبر Gamma
        if fin and config.GAMMA_API_KEY:
            await safe_send(bot, chat_id, "🎨 جاري توليد العرض التقديمي (قد يستغرق دقائق)...")
            try:
                deck = await asyncio.to_thread(
                    PresentationAgent().generate_pitch_deck,
                    data["project_idea"], 
                    data["location"], 
                    data["capital"],
                    market_html, 
                    fin.metrics, 
                    fin.undocumented, 
                    fin.total_assumptions, 
                    tracker
                )
                if deck and deck.get("url"):
                    tracker.stage("presentation", "ok")
                    extra = f"\n📥 تصدير: {esc(deck['export_url'])}" if deck.get("export_url") else ""
                    await safe_send(bot, chat_id, f"🎯 العرض جاهز:\n{esc(deck['url'])}{extra}")
                else:
                    tracker.stage("presentation", "failed: لم يُرجع رابطاً")
                    await safe_send(bot, chat_id, "⚠️ لم يكتمل توليد العرض (راجع السجلات والخطة).")
            except Exception as exc:
                logger.exception("presentation")
                tracker.stage("presentation", f"failed: {type(exc).__name__}")
                await safe_send(bot, chat_id, "⚠️ تعذّر توليد العرض.")
        else:
            tracker.stage("presentation", "skipped: " + ("no model" if not fin else "GAMMA_API_KEY"))

        done = all(v.startswith("ok") for v in tracker.stages.values())
        await safe_send(bot, chat_id, "✅ اكتملت المراحل." if done else "ℹ️ انتهى التنفيذ مع مراحل ناقصة (انظر الرسائل أعلاه).")
    finally:
        RUNNING.discard(user_id)
        await finish_tracker(app, tracker)


# ----------------------------------------------------------------------------- مسار الشركات القائمة
async def existing_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["company_name"] = update.message.text.strip()[:200]
    await update.message.reply_text("📌 <b>ما القطاع ونموذج العمل؟</b> (مثال: تجزئة B2C، مقاولات، SaaS)", parse_mode="HTML")
    return EXISTING_SECTOR


async def existing_sector(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["sector"] = update.message.text.strip()[:200]
    await update.message.reply_text("📌 <b>ما هدف التقرير؟</b> (تراجع أرباح، تسعير، تقييم، توسع)", parse_mode="HTML")
    return EXISTING_CHALLENGE


async def existing_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["challenge"] = update.message.text.strip()[:300]
    await update.message.reply_text(
        "📎 ارفع القوائم المالية (PDF/Excel) الآن، أو اكتب «بدون ملفات».", 
        parse_mode="HTML"
    )
    return EXISTING_DOCS


async def existing_docs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    d = context.user_data
    d["has_file"], d["parsed_pages"] = False, 0
    doc = update.message.document
    if doc:
        if (doc.file_size or 0) > config.MAX_UPLOAD_MB * 1024 * 1024:
            await update.message.reply_text(f"⚠️ الملف أكبر من {config.MAX_UPLOAD_MB:g} ميغابايت.")
            return EXISTING_DOCS
        await update.message.reply_text("⏳ جاري قراءة المستند...")
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            raw = bytes(await tg_file.download_as_bytearray())
            text, pages = await parse_financial_document(raw, doc.file_name or "file")
            d.update(
                has_file=True, 
                parsed_pages=pages, 
                file_name=doc.file_name,
                extracted_chars=len(text)
            )
            DOCS[update.effective_user.id] = text  # حفظ مؤقت في الذاكرة لتغذية وحدة التشخيص
            msg = f"✅ تمت قراءة «{esc(doc.file_name)}» ({pages} قسم/صفحة)."
        except DocParseError as exc:
            msg = f"⚠️ {esc(exc)}"
        except Exception:
            logger.exception("doc parse")
            msg = "⚠️ تعذّرت قراءة المستند."
        await update.message.reply_text(msg, parse_mode="HTML")
    else:
        await update.message.reply_text("تم المتابعة دون ملفات.")
        
    await update.message.reply_text(
        "🏛 <b>ملخص الطلب:</b>\n"
        f"• الشركة: {esc(d['company_name'])}\n• القطاع: {esc(d['sector'])}\n• الهدف: {esc(d['challenge'])}\n"
        f"• المرفقات: {'نعم' if d['has_file'] else 'لا'}\n\nهل أحفظ الطلب؟ (نعم / إلغاء)",
        parse_mode="HTML"
    )
    return EXISTING_CONFIRM


async def existing_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_yes(update.message.text):
        await update.message.reply_text("تم الإلغاء. أرسل /start للبدء من جديد.")
        return ConversationHandler.END
    d = context.user_data
    tracker = CostTracker("EXISTING_DIAGNOSTIC_REQUEST", update.effective_user.id)
    tracker.add_llama_pages(d.get("parsed_pages", 0))
    tracker.stage("diagnostic_analysis", "skipped: الوحدة قيد التطوير")
    await update.message.reply_text(
        "📝 تم حفظ الطلب وقراءة المستندات، لكن <b>التحليل التشخيصي الآلي لم يُفعَّل بعد</b>؛ "
        "لن أصدر تقريراً غير حقيقي. سأبلغ المدير بالطلب.",
        parse_mode="HTML"
    )
    await admin_notify(
        context.application,
        f"📥 <b>طلب تشخيص شركة</b>\n• {esc(d.get('company_name'))} | {esc(d.get('sector'))}\n"
        f"• الهدف: {esc(d.get('challenge'))}\n• ملف: {esc(d.get('file_name', 'لا'))}"
    )
    await finish_tracker(context.application, tracker)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("تم الإلغاء.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("خطأ غير معالج", exc_info=context.error)
    await admin_notify(
        context.application, 
        f"❗ خطأ في البوت: <code>{esc(type(context.error).__name__)}: {esc(str(context.error)[:300])}</code>"
    )


async def post_init(app: Application) -> None:
    if not config.ALLOWED_USER_IDS:
        logger.warning("ALLOWED_USER_IDS/ADMIN_CHAT_ID غير مضبوط — البوت سيرفض الجميع (تفشل مغلقة).")
    missing = config.missing_features()
    if missing:
        logger.warning("مراحل معطلة لغياب المفاتيح: %s", "، ".join(missing))


def build_application() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN مفقود في إعدادات البيئة")
    os.makedirs(os.path.dirname(config.PERSISTENCE_PATH) or ".", exist_ok=True)
    persistence = PicklePersistence(
        filepath=config.PERSISTENCE_PATH,
        store_data=PersistenceInput(bot_data=False, chat_data=False, callback_data=False)
    )
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).persistence(persistence).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start, filters=AUTH)],
        states={
            CHOOSE_TRACK: [MessageHandler(TEXT, choose_track)],
            NEW_IDEA: [MessageHandler(TEXT, new_idea)],
            NEW_LOCATION: [MessageHandler(TEXT, new_location)],
            NEW_CAPITAL: [MessageHandler(TEXT, new_capital)],
            NEW_CONFIRM: [MessageHandler(TEXT, new_confirm)],
            EXISTING_COMPANY_NAME: [MessageHandler(TEXT, existing_company_name)],
            EXISTING_SECTOR: [MessageHandler(TEXT, existing_sector)],
            EXISTING_CHALLENGE: [MessageHandler(TEXT, existing_challenge)],
            EXISTING_DOCS: [
                MessageHandler(filters.Document.ALL & AUTH, existing_docs), 
                MessageHandler(TEXT, existing_docs)
            ],
            EXISTING_CONFIRM: [MessageHandler(TEXT, existing_confirm)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel, filters=AUTH), 
            CommandHandler("start", start, filters=AUTH)
        ],
        conversation_timeout=3600, 
        name="castlix_main", 
        persistent=True,
    )
    app.add_handler(CommandHandler("whoami", whoami))  # مفتوح للجميع لمعرفة المعرف فقط
    app.add_handler(conv)
    app.add_handler(MessageHandler(~AUTH & ~filters.Regex(r"^/whoami"), deny), group=1)
    app.add_error_handler(on_error)
    return app


def main() -> None:
    app = build_application()
    logger.info("Castlix Engine is running (allowed users: %d)", len(config.ALLOWED_USER_IDS))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

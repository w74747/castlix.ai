"""
bot.py — بوت Castlix Advisory على تليجرام (نسخة الذكاء الاستشاري والفواتير).

الميزات المضافة:
  * منسق حوار ذكي (ChatOrchestrator) يفهم اللهجات ويدير الاستكشاف بأسلوب إنساني.
  * نظام توليد عروض أسعار وفواتير رسمية PDF عبر أمر /invoice.
  * استمرارية كاملة، أمان Fail-Closed، ومهام خلفية غير حاجبة.
"""
import asyncio
import logging
import os
import uuid
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
from agents.chat_orchestrator import ChatOrchestrator
from agents.finance import FinancialModelingAgent
from agents.market import MarketResearchAgent
from agents.presentation import PresentationAgent
from utils.cost_tracker import CostTracker
from utils.doc_parser import DocParseError, parse_financial_document
from utils.invoice_generator import InvoiceGenerator
from utils.telegram_text import esc, safe_send

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger("CastlixEngine")

(
    CHOOSE_TRACK,
    NEW_CONSULTATIVE_CHAT,
    NEW_CONFIRM,
    EXISTING_COMPANY_NAME,
    EXISTING_SECTOR,
    EXISTING_CHALLENGE,
    EXISTING_DOCS,
    EXISTING_CONFIRM,
    INVOICE_DETAILS,
) = range(9)

# فلتر الصلاحية: تفشل مغلقة تلقائياً لحماية النظام
AUTH = filters.User(user_id=list(config.ALLOWED_USER_IDS))
TEXT = filters.TEXT & ~filters.COMMAND & AUTH
YES = ("نعم", "yes", "y", "ok", "تأكيد", "ابدأ", "توكل على الله", "تمام")

RUNNING: set = set()
DOCS: Dict[int, str] = {}
orchestrator = ChatOrchestrator()
invoice_gen = InvoiceGenerator()


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
            "أضف هذا الرقم إلى ALLOWED_USER_IDS في إعدادات الخادم لتفعيل الوصول."
        )


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"معرّفك: {update.effective_user.id}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    keyboard = [
        ["1️⃣ دراسة جدوى مشروع جديد", "2️⃣ تحليل وتشخيص شركة قائمة"],
        ["📄 طلب عرض سعر / فاتورة"]
    ]
    await update.message.reply_text(
        "🏛 <b>Castlix Advisory — القلعة الرقمية للاستشارات</b>\n"
        "أهلاً بك. أنا مستشارك الاستثماري والمالي. اختر مسار العمل المطلوب:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode="HTML"
    )
    return CHOOSE_TRACK


async def choose_track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    if "مشروع جديد" in choice:
        context.user_data["service_type"] = "NEW_PROJECT"
        await update.message.reply_text(
            "🚀 <b>مرحباً بك في مسار دراسة الجدوى الاستثمارية</b>\n\n"
            "تحدث معي بأريحية وبأي لهجة تفضلها؛ اكتب فكرة مشروعك، وأين تخطط للتأسيس، "
            "ورأس المال التقريبي إن وجد (أو اطلب مني تقديره).\n\n"
            "👈 <i>أخبرني، ما هو المشروع الذي تفكر في إطلاقه؟</i>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        return NEW_CONSULTATIVE_CHAT

    if "شركة قائمة" in choice:
        context.user_data["service_type"] = "EXISTING_BUSINESS"
        await update.message.reply_text(
            "📈 <b>التشخيص المالي والتنافسي</b>\n\n"
            "⚠️ هذا المسار قيد التطوير: نقوم باستلام بياناتك وقوائمك المالية بأمان لحفظ الطلب ودراسته.\n\n"
            "👈 <b>ما اسم شركتك وفي أي دولة ونشاط تعمل؟</b>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        return EXISTING_COMPANY_NAME

    if "عرض سعر" in choice or "فاتورة" in choice:
        return await start_invoice_flow(update, context)

    await update.message.reply_text("يرجى اختيار أحد الخيارات من القائمة.")
    return CHOOSE_TRACK


# ----------------------------------------------------------------------------- الحوار الاستشاري البشري
async def consultative_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_msg = update.message.text.strip()
    tracker = CostTracker("AI_INTAKE", update.effective_user.id)
    
    # استخلاص المعطيات عبر النموذج اللغوي دون تجميد البوت
    intake = await asyncio.to_thread(
        orchestrator.process_user_input,
        user_msg,
        context.user_data,
        tracker
    )

    if intake.project_idea:
        context.user_data["project_idea"] = intake.project_idea
    if intake.location:
        context.user_data["location"] = intake.location
    if intake.capital:
        context.user_data["capital"] = intake.capital

    # إذا اكتملت المعطيات الأساسية الثلاثة، نطلب التأكيد للإطلاق
    if intake.is_ready_for_pipeline and context.user_data.get("project_idea") and context.user_data.get("location"):
        d = context.user_data
        capital_disp = d.get("capital") or "تقدير آلي حسب معايير السوق"
        await update.message.reply_text(
            f"{esc(intake.conversational_reply)}\n\n"
            "🏛 <b>الملخص الاستثماري المستخلص:</b>\n"
            f"• <b>المشروع:</b> {esc(d['project_idea'])}\n"
            f"• <b>الموقع:</b> {esc(d['location'])}\n"
            f"• <b>رأس المال:</b> {esc(capital_disp)}\n\n"
            "هل ترغب في إطلاق محرك دراسة الجدوى والنمذجة المالية الآن؟ (نعم / تعديل)",
            parse_mode="HTML"
        )
        return NEW_CONFIRM

    # في حال وجود نواقص، يتابع الحوار بأسلوب إنساني ذكي
    await update.message.reply_text(esc(intake.conversational_reply), parse_mode="HTML")
    return NEW_CONSULTATIVE_CHAT


async def new_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_yes(update.message.text):
        await update.message.reply_text(
            "تمام، أخبرني بالتعديلات أو التفاصيل الإضافية التي ترغب في توضيحها:",
            reply_markup=ReplyKeyboardRemove()
        )
        return NEW_CONSULTATIVE_CHAT

    uid = update.effective_user.id
    if uid in RUNNING:
        await update.message.reply_text("⏳ لديك دراسة قيد الإعداد بالفعل. انتظر اكتمالها.")
        return ConversationHandler.END

    RUNNING.add(uid)
    await update.message.reply_text("⏳ بدأ محرك Castlix العمل في الخلفية. سأرسل لك المخرجات مرحلياً فور جاهزيتها.")
    data = dict(context.user_data)
    context.application.create_task(run_new_project(context.application, update.effective_chat.id, uid, data))
    return ConversationHandler.END


async def run_new_project(app: Application, chat_id: int, user_id: int, data: Dict[str, Any]) -> None:
    """المسار الكامل غير الحاجب لتحليل السوق وبناء الإكسيل وتوليد الشرائح."""
    tracker = CostTracker("NEW_FEASIBILITY", user_id)
    bot = app.bot
    market_html = ""
    try:
        # 1. مسح السوق (Tavily)
        if config.TAVILY_API_KEY:
            await safe_send(bot, chat_id, "🔎 جاري مسح المشهد التنافسي ومؤشرات السوق...")
            try:
                agent = MarketResearchAgent()
                market = await asyncio.to_thread(agent.conduct_research, data["project_idea"], data["location"], tracker)
                market_html = market.get("structured_report", "")
                tracker.stage("market", "ok")
                await safe_send(bot, chat_id, market_html)
            except Exception as exc:
                logger.exception("market failure")
                tracker.stage("market", f"failed: {type(exc).__name__}")
                await safe_send(bot, chat_id, "⚠️ تعذّر مسح السوق؛ جاري الانتقال للنموذج المالي.")
        else:
            tracker.stage("market", "skipped: TAVILY_API_KEY")

        # 2. النموذج المالي التفاعلي (openpyxl + finance_core)
        await safe_send(bot, chat_id, "📐 جاري بناء النموذج المالي والسيناريوهات الحسابية...")
        fin = None
        try:
            fin = await asyncio.to_thread(
                FinancialModelingAgent().generate_financial_model,
                data["project_idea"],
                data["location"],
                data.get("capital", "ابحث أنت"),
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
                f"🏛 النموذج المالي لـ {data['project_idea']}\n"
                f"• NPV (بدون قيمة نهائية): ${m['npv_explicit']:,.0f}\n"
                f"• IRR (شاملاً القيمة النهائية): {irr_txt}\n"
                f"• فترة الاسترداد: {payback}\n"
                f"• حالة الفرضيات: {fin.undocumented}/{fin.total_assumptions} غير موثقة (Low)"
            )
            await bot.send_document(chat_id=chat_id, document=buf, caption=caption[:1000])
            for w in fin.warnings:
                await safe_send(bot, chat_id, f"⚠️ {esc(w)}")
        except Exception as exc:
            logger.exception("finance error")
            tracker.stage("finance", f"failed: {type(exc).__name__}")
            await safe_send(bot, chat_id, "❌ تعذّر بناء النموذج المالي. تم إشعار الإدارة.")

        # 3. العرض التقديمي (Gamma API v1.0)
        if fin and config.GAMMA_API_KEY:
            await safe_send(bot, chat_id, "🎨 جاري إعداد العرض الاستثماري للشركاء...")
            try:
                deck = await asyncio.to_thread(
                    PresentationAgent().generate_pitch_deck,
                    data["project_idea"],
                    data["location"],
                    data.get("capital", ""),
                    market_html,
                    fin.metrics,
                    fin.undocumented,
                    fin.total_assumptions,
                    tracker
                )
                if deck and deck.get("url"):
                    tracker.stage("presentation", "ok")
                    extra = f"\n📥 تصدير: {esc(deck['export_url'])}" if deck.get("export_url") else ""
                    await safe_send(bot, chat_id, f"🎯 العرض الاستثماري جاهز:\n{esc(deck['url'])}{extra}")
                else:
                    tracker.stage("presentation", "failed")
                    await safe_send(bot, chat_id, "⚠️ لم يكتمل بناء العرض التقديمي.")
            except Exception as exc:
                logger.exception("presentation error")
                tracker.stage("presentation", f"failed: {type(exc).__name__}")
        else:
            tracker.stage("presentation", "skipped")

        await safe_send(bot, chat_id, "✅ اكتملت مخرجات الدراسة الاستثمارية الأولية بنجاح.")
    finally:
        RUNNING.discard(user_id)
        await finish_tracker(app, tracker)


# ----------------------------------------------------------------------------- مسار الفواتير وعروض الأسعار
async def start_invoice_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📄 <b>إنشاء عرض سعر أو فاتورة رسمية (PDF)</b>\n\n"
        "أرسل البيانات بالصيغة التالية (أو اكتبها في سطر واحد):\n"
        "<code>نوع الوثيقة (فاتورة / عرض سعر) | اسم العميل | اسم الشركة | المبلغ | العملة</code>\n\n"
        "<i>مثال:</i>\n"
        "<code>عرض سعر | سالم الحارثي | الخليج للتطوير | 1200 | OMR</code>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )
    return INVOICE_DETAILS


async def handle_invoice_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    parts = [p.strip() for p in text.split("|")]
    
    if len(parts) < 4:
        await update.message.reply_text(
            "⚠️ يرجى التأكد من كتابة الحقول مفصولة بعلامة (|).\nمثال: عرض سعر | سالم الحارثي | الخليج للتطوير | 1200 | OMR"
        )
        return INVOICE_DETAILS

    doc_type = "INVOICE" if "فاتورة" in parts[0] else "QUOTATION"
    client_name = parts[1]
    client_org = parts[2]
    
    try:
        rate = float(parts[3].replace(",", ""))
    except ValueError:
        rate = 500.0

    currency = parts[4].upper() if len(parts) > 4 else "USD"
    doc_number = f"CAS-{uuid.uuid4().hex[:6].upper()}"

    await update.message.reply_text("⏳ جاري توليد وثيقة PDF الرسمية بالهوية المعتمدة...")

    items = [{
        "desc": "خدمة إعداد دراسة جدوى ونمذجة مالية شاملة (Castlix Feasibility)",
        "qty": 1,
        "rate": rate
    }]

    pdf_bytes = await asyncio.to_thread(
        invoice_gen.generate_document,
        doc_type=doc_type,
        doc_number=doc_number,
        client_name=client_name,
        client_org=client_org,
        items=items,
        currency=currency,
        notes="الدفع مستحق خلال 14 يوماً من تاريخ الإصدار عبر التحويل البنكي المباشر."
    )

    buf = BytesIO(pdf_bytes)
    buf.name = f"{doc_type}_{doc_number}.pdf"
    
    caption = f"📄 <b>تم إصدار الوثيقة الرسمية</b>\n• النوع: {doc_type}\n• الرقم: #{doc_number}\n• العميل: {client_name}"
    await update.message.reply_document(document=buf, caption=caption, parse_mode="HTML")
    return ConversationHandler.END


# ----------------------------------------------------------------------------- مسار الشركات القائمة
async def existing_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["company_name"] = update.message.text.strip()[:200]
    await update.message.reply_text("📌 <b>ما القطاع ونموذج العمل؟</b>", parse_mode="HTML")
    return EXISTING_SECTOR


async def existing_sector(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["sector"] = update.message.text.strip()[:200]
    await update.message.reply_text("📌 <b>ما التحدي أو هدف الفحص؟</b> (تراجع أرباح، تسعير، توسع)", parse_mode="HTML")
    return EXISTING_CHALLENGE


async def existing_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["challenge"] = update.message.text.strip()[:300]
    await update.message.reply_text("📎 ارفع القوائم المالية (PDF/Excel) الآن، أو اكتب «بدون ملفات».", parse_mode="HTML")
    return EXISTING_DOCS


async def existing_docs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    d = context.user_data
    d["has_file"], d["parsed_pages"] = False, 0
    doc = update.message.document
    if doc:
        if (doc.file_size or 0) > config.MAX_UPLOAD_MB * 1024 * 1024:
            await update.message.reply_text(f"⚠️ الملف أكبر من {config.MAX_UPLOAD_MB:g} ميغابايت.")
            return EXISTING_DOCS
        await update.message.reply_text("⏳ جاري قراءة المستند واستخراج البيانات...")
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            raw = bytes(await tg_file.download_as_bytearray())
            text, pages = await parse_financial_document(raw, doc.file_name or "file")
            d.update(has_file=True, parsed_pages=pages, file_name=doc.file_name, extracted_chars=len(text))
            DOCS[update.effective_user.id] = text
            msg = f"✅ تمت قراءة «{esc(doc.file_name)}» ({pages} صفحة/جدول)."
        except DocParseError as exc:
            msg = f"⚠️ {esc(exc)}"
        except Exception:
            logger.exception("doc parse")
            msg = "⚠️ تعذّرت قراءة المستند."
        await update.message.reply_text(msg, parse_mode="HTML")
    else:
        await update.message.reply_text("تم المتابعة دون مرفقات.")

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
        "📝 تم حفظ الطلب بنجاح. سنراجع البيانات ونتواصل معك بالتقرير التشخيصي المعتمد.",
        parse_mode="HTML"
    )
    await admin_notify(
        context.application,
        f"📥 <b>طلب تشخيص شركة جديد</b>\n• {esc(d.get('company_name'))} | {esc(d.get('sector'))}\n"
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
        logger.warning("ALLOWED_USER_IDS غير مضبوط — البوت مغلق تلقائياً (Fail-Closed).")


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
        entry_points=[CommandHandler("start", start, filters=AUTH), CommandHandler("invoice", start_invoice_flow, filters=AUTH)],
        states={
            CHOOSE_TRACK: [MessageHandler(TEXT, choose_track)],
            NEW_CONSULTATIVE_CHAT: [MessageHandler(TEXT, consultative_chat)],
            NEW_CONFIRM: [MessageHandler(TEXT, new_confirm)],
            EXISTING_COMPANY_NAME: [MessageHandler(TEXT, existing_company_name)],
            EXISTING_SECTOR: [MessageHandler(TEXT, existing_sector)],
            EXISTING_CHALLENGE: [MessageHandler(TEXT, existing_challenge)],
            EXISTING_DOCS: [MessageHandler(filters.Document.ALL & AUTH, existing_docs), MessageHandler(TEXT, existing_docs)],
            EXISTING_CONFIRM: [MessageHandler(TEXT, existing_confirm)],
            INVOICE_DETAILS: [MessageHandler(TEXT, handle_invoice_details)],
        },
        fallbacks=[CommandHandler("cancel", cancel, filters=AUTH), CommandHandler("start", start, filters=AUTH)],
        conversation_timeout=3600,
        name="castlix_main",
        persistent=True,
    )
    app.add_handler(CommandHandler("whoami", whoami))
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

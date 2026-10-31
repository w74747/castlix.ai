"""
bot.py — بوت Castlix Advisory على تليجرام (النسخة الاستشارية والمؤسسية المحدثة).

الميزات المدمجة:
  * واجهة ترحيبية رصينة بأسلوب بيوت الخبرة والاستشارات العالمية.
  * منسق حوار ذكي (ChatOrchestrator) يفهم اللهجات ويدعم التبديل التلقائي بين النماذج (Auto-Failover).
  * تكامل دائم مع PostgreSQL لحفظ المشاريع، الفواتير، وسجلات التكاليف.
  * إدارة الجلسات والأقفال التشغيلية اللحظية عبر Redis.
  * توليد عروض أسعار وفواتير رسمية بصيغة PDF بالهوية المعتمدة عبر أمر /invoice.
  * أمان صارم (Fail-Closed) ومعالجة غير حاجبة (Non-blocking Tasks).
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
from database import Project, InvoiceRecord, SessionLocal, init_db
from redis_cache import cache
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

# حماية مشددة: النظام يفشل مغلقاً تلقائياً
AUTH = filters.User(user_id=list(config.ALLOWED_USER_IDS))
TEXT = filters.TEXT & ~filters.COMMAND & AUTH
YES = ("نعم", "yes", "y", "ok", "تأكيد", "ابدأ", "توكل على الله", "تمام")

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


# -----------------------------------------------------------------------------
# بوابات التحقق وإدارة الجلسات
# -----------------------------------------------------------------------------
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
        "أهلاً بك. أنا مستشارك الاستثماري والمالي. يرجى اختيار مسار العمل المطلوب:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode="HTML"
    )
    return CHOOSE_TRACK


async def choose_track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    if "مشروع جديد" in choice:
        context.user_data["service_type"] = "NEW_PROJECT"
        await update.message.reply_text(
            "🚀 <b>مسار دراسة الجدوى الاستثمارية والنمذجة المالية</b>\n\n"
            "أهلاً بك. يرجى تزويدي بفكرة المشروع، النطاق الجغرافي المستهدف، "
            "ورأس المال المبدئي المقترح (أو توضيح رغبتك في تقديره آلياً بحسب مؤشرات السوق).\n\n"
            "👈 <i>ما هو النشاط الاستثماري المقترح؟</i>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        return NEW_CONSULTATIVE_CHAT

    if "شركة قائمة" in choice:
        context.user_data["service_type"] = "EXISTING_BUSINESS"
        await update.message.reply_text(
            "📈 <b>التشخيص المالي والتنافسي للمنشآت القائمة</b>\n\n"
            "⚠️ هذا المسار قيد التطوير: نقوم باستلام بياناتك وقوائمك المالية بأمان لحفظ الطلب وفحصه.\n\n"
            "👈 <b>ما اسم الشركة وفي أي قطاع ودولة تعمل؟</b>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        return EXISTING_COMPANY_NAME

    if "عرض سعر" in choice or "فاتورة" in choice:
        return await start_invoice_flow(update, context)

    await update.message.reply_text("يرجى اختيار أحد الخيارات من القائمة.")
    return CHOOSE_TRACK


# -----------------------------------------------------------------------------
# طبقة الحوار الاستشاري الذكي
# -----------------------------------------------------------------------------
async def consultative_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_msg = update.message.text.strip()
    tracker = CostTracker("AI_INTAKE", update.effective_user.id)
    
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

    cache.set_session(update.effective_user.id, context.user_data)

    if intake.is_ready_for_pipeline and context.user_data.get("project_idea") and context.user_data.get("location"):
        d = context.user_data
        capital_disp = d.get("capital") or "تقدير آلي حسب معايير السوق"
        await update.message.reply_text(
            f"{esc(intake.conversational_reply)}\n\n"
            "🏛 <b>نطاق الدراسة المعتمد مبدئياً:</b>\n"
            f"• <b>المشروع:</b> {esc(d['project_idea'])}\n"
            f"• <b>الموقع الجغرافي:</b> {esc(d['location'])}\n"
            f"• <b>رأس المال:</b> {esc(capital_disp)}\n\n"
            "هل ترغب في إطلاق محرك أبحاث السوق والنمذجة المالية الآن؟ (نعم / تعديل)",
            parse_mode="HTML"
        )
        return NEW_CONFIRM

    await update.message.reply_text(esc(intake.conversational_reply), parse_mode="HTML")
    return NEW_CONSULTATIVE_CHAT


async def new_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_yes(update.message.text):
        await update.message.reply_text(
            "حسناً، تفضل بتوضيح التعديلات أو أي تفاصيل إضافية ترغب في تعديلها:",
            reply_markup=ReplyKeyboardRemove()
        )
        return NEW_CONSULTATIVE_CHAT

    uid = update.effective_user.id
    
    if not cache.acquire_lock(uid, timeout_seconds=300):
        await update.message.reply_text("⏳ لديك دراسة قيد الإعداد والمعالجة بالفعل. يرجى الانتظار حتى اكتمالها.")
        return ConversationHandler.END

    await update.message.reply_text("⏳ بدأ محرك Castlix العمل والتحليل في الخلفية. ستصلك المخرجات مرحلياً فور جاهزيتها.")
    data = dict(context.user_data)
    context.application.create_task(run_new_project(context.application, update.effective_chat.id, uid, data))
    return ConversationHandler.END


async def run_new_project(app: Application, chat_id: int, user_id: int, data: Dict[str, Any]) -> None:
    """معالجة غير حاجبة لمسح السوق والنمذجة المالية وحفظ السجلات في PostgreSQL."""
    tracker = CostTracker("NEW_FEASIBILITY", user_id)
    bot = app.bot
    market_html = ""
    fin = None
    deck_url = None
    project_status = "completed"

    try:
        # 1. أبحاث ومسح السوق
        if config.TAVILY_API_KEY:
            await safe_send(bot, chat_id, "🔎 جاري مسح المشهد التنافسي ومؤشرات السوق المستهدف...")
            try:
                agent = MarketResearchAgent()
                market = await asyncio.to_thread(agent.conduct_research, data["project_idea"], data["location"], tracker)
                market_html = market.get("report_html", "")
                tracker.stage("market", "ok")
                await safe_send(bot, chat_id, market_html)
            except Exception as exc:
                logger.exception("market failure")
                tracker.stage("market", f"failed: {type(exc).__name__}")
                await safe_send(bot, chat_id, "⚠️ تعذّر استكمال مسح السوق آلياً؛ جاري الانتقال للنموذج المالي.")
        else:
            tracker.stage("market", "skipped: TAVILY_API_KEY")

        # 2. بناء النموذج المالي التفاعلي
        await safe_send(bot, chat_id, "📐 جاري بناء النموذج المالي التفاعلي وهيكلة القوائم والسيناريوهات...")
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
                f"🏛 النموذج المالي التفاعلي: {data['project_idea']}\n"
                f"• صافي القيمة الحالية (NPV): ${m['npv_explicit']:,.0f}\n"
                f"• معدل العائد الداخلي (IRR): {irr_txt}\n"
                f"• فترة الاسترداد المتوقعة: {payback}\n"
                f"• التدقيق على الفرضيات: {fin.undocumented}/{fin.total_assumptions} غير موثقة"
            )
            await bot.send_document(chat_id=chat_id, document=buf, caption=caption[:1000])
            for w in fin.warnings:
                await safe_send(bot, chat_id, f"⚠️ {esc(w)}")
        except Exception as exc:
            logger.exception("finance error")
            tracker.stage("finance", f"failed: {type(exc).__name__}")
            project_status = "failed"
            await safe_send(bot, chat_id, "❌ تعذّر بناء النموذج المالي. تم إشعار الإدارة الفنية.")

        # 3. العرض الاستثماري للشركاء (Pitch Deck)
        if fin and config.GAMMA_API_KEY:
            await safe_send(bot, chat_id, "🎨 جاري إعداد العرض الاستثماري التنفيذي للشركاء...")
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
                    deck_url = deck.get("url")
                    tracker.stage("presentation", "ok")
                    extra = f"\n📥 تصدير: {esc(deck['export_url'])}" if deck.get("export_url") else ""
                    await safe_send(bot, chat_id, f"🎯 العرض الاستثماري مكتمل وجاهز:\n{esc(deck_url)}{extra}")
                else:
                    tracker.stage("presentation", "failed")
                    await safe_send(bot, chat_id, "⚠️ لم يكتمل بناء العرض التقديمي.")
            except Exception as exc:
                logger.exception("presentation error")
                tracker.stage("presentation", f"failed: {type(exc).__name__}")
        else:
            tracker.stage("presentation", "skipped")

        # 4. توثيق وحفظ سجل المشروع في PostgreSQL
        if SessionLocal:
            db = None
            try:
                db = SessionLocal()
                p_record = Project(
                    user_id=user_id,
                    project_idea=data.get("project_idea", ""),
                    location=data.get("location", ""),
                    capital_text=data.get("capital", ""),
                    capital_usd=fin.capital_usd if fin else None,
                    status=project_status,
                    market_summary=market_html[:2000] if market_html else None,
                    finance_metrics=fin.metrics if fin else None,
                    deck_url=deck_url
                )
                db.add(p_record)
                db.commit()
                logger.info("تم حفظ المشروع ومؤشراته في جدول projects بـ PostgreSQL.")
            except Exception as exc:
                logger.error(f"فشل حفظ المشروع في قاعدة البيانات: {exc}")
                if db:
                    db.rollback()
            finally:
                if db:
                    db.close()

        await safe_send(bot, chat_id, "✅ اكتملت مخرجات الدراسة الاستثمارية والنمذجة المالية بنجاح.")
    finally:
        cache.release_lock(user_id)
        await finish_tracker(app, tracker)


# -----------------------------------------------------------------------------
# مسار الفواتير وعروض الأسعار الرسمية (PDF)
# -----------------------------------------------------------------------------
async def start_invoice_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📄 <b>إصدار عرض سعر أو فاتورة رسمية (PDF)</b>\n\n"
        "يرجى إرسال تفاصيل الوثيقة بصيغة مفصولة بعلامة (|) كالتالي:\n"
        "<code>نوع الوثيقة (فاتورة / عرض سعر) | اسم العميل | المؤسسة أو الشركة | القيمة | العملة</code>\n\n"
        "<i>مثال تطبيقي:</i>\n"
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
            "⚠️ التنسيق غير مكتمل. يرجى إرسال الحقول مفصولة بعلامة (|).\nمثال: عرض سعر | سالم الحارثي | الخليج للتطوير | 1200 | OMR"
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
        notes="الدفع مستحق خلال 14 يوماً من تاريخ الإصدار عبر التحويل البنكي المعتمد."
    )

    if SessionLocal:
        db = None
        try:
            db = SessionLocal()
            inv_record = InvoiceRecord(
                doc_number=doc_number,
                doc_type=doc_type,
                client_name=client_name,
                client_org=client_org,
                amount=rate,
                currency=currency,
                status="issued"
            )
            db.add(inv_record)
            db.commit()
            logger.info("تم توثيق الفاتورة في جدول invoices بـ PostgreSQL.")
        except Exception as exc:
            logger.error(f"فشل حفظ الفاتورة في قاعدة البيانات: {exc}")
            if db:
                db.rollback()
        finally:
            if db:
                db.close()

    buf = BytesIO(pdf_bytes)
    buf.name = f"{doc_type}_{doc_number}.pdf"
    
    caption = f"📄 <b>تم إصدار الوثيقة بنجاح</b>\n• النوع: {doc_type}\n• الرقم المرجعي: #{doc_number}\n• العميل: {client_name}"
    await update.message.reply_document(document=buf, caption=caption, parse_mode="HTML")
    return ConversationHandler.END


# -----------------------------------------------------------------------------
# مسار تشخيص وفحص الشركات القائمة
# -----------------------------------------------------------------------------
async def existing_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["company_name"] = update.message.text.strip()[:200]
    await update.message.reply_text("📌 <b>ما هو القطاع ونموذج العمل الحالي؟</b>", parse_mode="HTML")
    return EXISTING_SECTOR


async def existing_sector(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["sector"] = update.message.text.strip()[:200]
    await update.message.reply_text("📌 <b>ما هو التحدي الرئيسي أو هدف التشخيص؟</b> (هوامش الربحية، سياسات التسعير، التوسع)", parse_mode="HTML")
    return EXISTING_CHALLENGE


async def existing_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["challenge"] = update.message.text.strip()[:300]
    await update.message.reply_text("📎 يمكنك إرفاق القوائم المالية (PDF أو Excel) الآن، أو كتابة «بدون مرفقات».", parse_mode="HTML")
    return EXISTING_DOCS


async def existing_docs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    d = context.user_data
    d["has_file"], d["parsed_pages"] = False, 0
    doc = update.message.document
    if doc:
        if (doc.file_size or 0) > config.MAX_UPLOAD_MB * 1024 * 1024:
            await update.message.reply_text(f"⚠️ حجم الملف يتجاوز الحد المسموح به ({config.MAX_UPLOAD_MB:g} ميغابايت).")
            return EXISTING_DOCS
        await update.message.reply_text("⏳ جاري فحص المستند واستخراج البيانات المحاسبية...")
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            raw = bytes(await tg_file.download_as_bytearray())
            text, pages = await parse_financial_document(raw, doc.file_name or "file")
            d.update(has_file=True, parsed_pages=pages, file_name=doc.file_name, extracted_chars=len(text))
            DOCS[update.effective_user.id] = text
            msg = f"✅ تمت قراءة الملف «{esc(doc.file_name)}» بنجاح ({pages} صفحة/جدول)."
        except DocParseError as exc:
            msg = f"⚠️ {esc(exc)}"
        except Exception:
            logger.exception("doc parse error")
            msg = "⚠️ تعذّرت قراءة المستند بالشكل المطلوب."
        await update.message.reply_text(msg, parse_mode="HTML")
    else:
        await update.message.reply_text("تمت المتابعة دون إرفاق ملفات.")

    await update.message.reply_text(
        "🏛 <b>ملخص طلب التشخيص:</b>\n"
        f"• المنشأة: {esc(d['company_name'])}\n• القطاع: {esc(d['sector'])}\n• الهدف: {esc(d['challenge'])}\n"
        f"• المرفقات: {'مرفقة' if d['has_file'] else 'غير متوفرة'}\n\nهل ترغب في اعتماد وحفظ الطلب؟ (نعم / إلغاء)",
        parse_mode="HTML"
    )
    return EXISTING_CONFIRM


async def existing_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_yes(update.message.text):
        await update.message.reply_text("تم إلغاء الطلب. يمكنك إرسال /start للبدء مجدداً.")
        return ConversationHandler.END
    d = context.user_data
    tracker = CostTracker("EXISTING_DIAGNOSTIC_REQUEST", update.effective_user.id)
    tracker.add_llama_pages(d.get("parsed_pages", 0))
    tracker.stage("diagnostic_analysis", "skipped: قيد التطوير الميداني")
    await update.message.reply_text(
        "📝 تم تسجيل الطلب بنجاح. سيتم مراجعة البيانات وموافاتكم بتقرير الفحص التشخيصي المعتمد.",
        parse_mode="HTML"
    )
    await admin_notify(
        context.application,
        f"📥 <b>طلب تشخيص منشأة جديد</b>\n• {esc(d.get('company_name'))} | {esc(d.get('sector'))}\n"
        f"• الهدف: {esc(d.get('challenge'))}\n• المرفقات: {esc(d.get('file_name', 'بدون ملف'))}"
    )
    await finish_tracker(context.application, tracker)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("تم إلغاء الإجراء الحالي.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("خطأ تشغيلي غير معالج", exc_info=context.error)
    await admin_notify(
        context.application, 
        f"❗ تنبيه تشغيلي: <code>{esc(type(context.error).__name__)}: {esc(str(context.error)[:300])}</code>"
    )


async def post_init(app: Application) -> None:
    init_db()
    if not config.ALLOWED_USER_IDS:
        logger.warning("ALLOWED_USER_IDS غير مضبوط — النظام مغلق تلقائياً (Fail-Closed).")


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
        entry_points=[
            CommandHandler("start", start, filters=AUTH),
            CommandHandler("invoice", start_invoice_flow, filters=AUTH)
        ],
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

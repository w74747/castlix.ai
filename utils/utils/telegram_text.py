"""أدوات نصوص تليجرام: تهريب HTML وتقسيم الرسائل الطويلة وإرسال آمن."""
import html
import logging
from typing import List

from telegram.error import BadRequest

logger = logging.getLogger("CastlixTelegramText")
MAX_LEN = 3900  # حد تليجرام 4096؛ هامش أمان


def esc(value) -> str:
    """تهريب أي نص قادم من المستخدم أو من الويب قبل وضعه في رسالة HTML."""
    return html.escape(str(value if value is not None else ""), quote=False)


def chunk(text: str, size: int = MAX_LEN) -> List[str]:
    parts, buf = [], ""
    for line in text.split("\n"):
        while len(line) > size:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:size])
            line = line[size:]
        if len(buf) + len(line) + 1 > size:
            parts.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        parts.append(buf)
    return parts or [""]


async def safe_send(bot, chat_id: int, text: str, **kw) -> None:
    """يرسل HTML، وعند فشل التحليل يعيد المحاولة كنص عادي بدل أن يسقط المسار كله."""
    for part in chunk(text):
        try:
            await bot.send_message(
                chat_id=chat_id, 
                text=part, 
                parse_mode="HTML",
                disable_web_page_preview=True, 
                **kw
            )
        except BadRequest as exc:
            logger.warning("فشل HTML (%s)، إعادة كنص عادي", exc)
            fallback_text = html.unescape(
                part.replace("<b>", "")
                    .replace("</b>", "")
                    .replace("<i>", "")
                    .replace("</i>", "")
                    .replace("<code>", "")
                    .replace("</code>", "")
            )
            await bot.send_message(chat_id=chat_id, text=fallback_text, **kw)

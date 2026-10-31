"""
telegram_text.py — أدوات معالجة نصوص تليجرام وإرسالها بأمان.

يوفر هذا الملف:
  - تهريب أحرف HTML الخاصة (esc) لمنع أخطاء التنسيق.
  - تقطيع النصوص الطويلة (chunk) لتجاوز حد 4096 حرف في تليجرام.
  - إرسال الرسائل الطويلة مجزأة بأمان (safe_send).
"""
import html
from typing import List
from telegram import Bot
from telegram.error import TelegramError


def esc(text: str) -> str:
    """تهريب رموز HTML لمنع كسر تنسيق الرسائل في تليجرام."""
    if not text:
        return ""
    return html.escape(str(text), quote=True)


def chunk(text: str, limit: int = 3900) -> List[str]:
    """تقطيع النصوص الطويلة إلى أجزاء لا تتجاوز حد تليجرام مع الحفاظ على الأسطر."""
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    parts: List[str] = []
    current_part = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        if current_len + len(line) > limit:
            if current_part:
                parts.append("".join(current_part))
                current_part = []
                current_len = 0
            
            # إذا كان السطر الواحد أطول من الحد الأقصى
            while len(line) > limit:
                parts.append(line[:limit])
                line = line[limit:]

        current_part.append(line)
        current_len += len(line)

    if current_part:
        parts.append("".join(current_part))

    return parts


async def safe_send(bot: Bot, chat_id: int, text: str, parse_mode: str = "HTML") -> None:
    """إرسال نص طويل مجزأ إلى تليجرام لتجنب استثناء Message is too long."""
    if not text or not chat_id:
        return

    parts = chunk(text, limit=3900)
    for part in parts:
        try:
            await bot.send_message(chat_id=chat_id, text=part, parse_mode=parse_mode)
        except TelegramError:
            # إذا فشل التنسيق (مثل وسم HTML غير مغلق)، يتم الإرسال كنص خام
            await bot.send_message(chat_id=chat_id, text=part, parse_mode=None)

# utils.py
from __future__ import annotations

import os
from telegram import InlineKeyboardMarkup

MAX_MSG_LEN = 4000
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID")) if os.getenv("ADMIN_CHAT_ID") else None


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(list(rows))


def hp(path: str, text: str) -> str:
    return f"🏠 → {path}\n\n{text}"


def split_text(text: str, limit: int = MAX_MSG_LEN):
    if len(text) <= limit:
        return [text]
    parts = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        parts.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


async def safe_edit(query, context, text, reply_markup=None):
    parts = split_text(text)
    if len(parts) == 1:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
            return
        except Exception as e:
            err = str(e)
            print(f"⚠️ edit_message_text: {err}")
            if "message is not modified" in err:
                return
            if "Too Many Requests" in err or "retry after" in err.lower():
                return
            if ADMIN_ID:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"⚠️ Ошибка edit_message_text\n\n{err}",
                    )
                except Exception:
                    pass
            return
    try:
        await query.edit_message_text(parts[0])
    except Exception as e:
        print(f"⚠️ Первая часть не отредактирована: {e}")
    for i, part in enumerate(parts[1:], 1):
        try:
            await context.bot.send_message(chat_id=query.message.chat_id, text=part)
        except Exception as e:
            print(f"⚠️ Часть {i}: {e}")
    if reply_markup:
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="⬇️",
                reply_markup=reply_markup,
            )
        except Exception as e:
            print(f"⚠️ Кнопки: {e}")

import html
import logging
import os
from typing import Dict, Optional

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackContext, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Tokens and chat ids should be provided through environment variables for safety.
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0"))

# Mapping between forwarded messages (in the owner's chat) and the originating user ids.
FORWARDED_MESSAGE_MAP_KEY = "forwarded_message_map"


def ensure_map(context: ContextTypes.DEFAULT_TYPE) -> Dict[int, int]:
    """Return the shared mapping that links owner's chat messages to user ids."""
    data = context.application_data.setdefault(FORWARDED_MESSAGE_MAP_KEY, {})
    return data  # type: ignore[return-value]


def build_user_link(message: Message) -> str:
    """Create a clickable user link when a username is available."""
    user = message.from_user
    if not user:
        return "Неизвестный пользователь"

    if user.username:
        escaped_name = html.escape(user.full_name)
        return f"<a href='https://t.me/{user.username}'>{escaped_name}</a>"

    return html.escape(user.full_name)


def get_effective_text(message: Message) -> Optional[str]:
    """Return the text or caption of a message, if present."""
    return message.text or message.caption


async def forward_message_to_owner(update: Update, context: CallbackContext) -> None:
    """Forward any user message to the owner chat, preserving media where possible."""
    message = update.effective_message
    if not message or message.chat_id == OWNER_CHAT_ID:
        return

    user_link = build_user_link(message)
    mapping = ensure_map(context)

    sent_message: Optional[Message] = None

    if message.text:
        sent_message = await context.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text=f"Новое сообщение от {user_link}: {html.escape(message.text)}",
            parse_mode=ParseMode.HTML,
        )
    elif message.photo:
        sent_message = await context.bot.send_photo(
            chat_id=OWNER_CHAT_ID,
            photo=message.photo[-1].file_id,
            caption=f"Новое фото от {user_link}",
            parse_mode=ParseMode.HTML,
        )
    elif message.video:
        sent_message = await context.bot.send_video(
            chat_id=OWNER_CHAT_ID,
            video=message.video.file_id,
            caption=f"Новое видео от {user_link}",
            parse_mode=ParseMode.HTML,
        )
    elif message.voice:
        sent_message = await context.bot.send_voice(
            chat_id=OWNER_CHAT_ID,
            voice=message.voice.file_id,
            caption=f"Новое голосовое сообщение от {user_link}",
            parse_mode=ParseMode.HTML,
        )
    elif message.document:
        sent_message = await context.bot.send_document(
            chat_id=OWNER_CHAT_ID,
            document=message.document.file_id,
            caption=f"Документ от {user_link}",
            parse_mode=ParseMode.HTML,
        )

    if sent_message:
        mapping[sent_message.message_id] = message.from_user.id if message.from_user else 0


async def forward_reply_to_user(update: Update, context: CallbackContext) -> None:
    """Send the owner's reply back to the original user."""
    message = update.effective_message
    if not message or not message.reply_to_message:
        return

    mapping = ensure_map(context)
    target_user_id = mapping.get(message.reply_to_message.message_id)

    if not target_user_id:
        logger.info("No stored user id for replied message %s", message.reply_to_message.message_id)
        return

    if message.text:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=message.text,
            parse_mode=ParseMode.HTML,
        )
    elif message.photo:
        await context.bot.send_photo(
            chat_id=target_user_id,
            photo=message.photo[-1].file_id,
            caption=get_effective_text(message),
            parse_mode=ParseMode.HTML,
        )
    elif message.video:
        await context.bot.send_video(
            chat_id=target_user_id,
            video=message.video.file_id,
            caption=get_effective_text(message),
            parse_mode=ParseMode.HTML,
        )
    elif message.voice:
        await context.bot.send_voice(
            chat_id=target_user_id,
            voice=message.voice.file_id,
            caption=get_effective_text(message),
            parse_mode=ParseMode.HTML,
        )
    elif message.document:
        await context.bot.send_document(
            chat_id=target_user_id,
            document=message.document.file_id,
            caption=get_effective_text(message),
            parse_mode=ParseMode.HTML,
        )


def main() -> None:
    if TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or OWNER_CHAT_ID == 0:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN and OWNER_CHAT_ID environment variables")

    application = Application.builder().token(TOKEN).build()

    user_filters = (~filters.Chat(OWNER_CHAT_ID)) & (
        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE | filters.Document.ALL
    )

    application.add_handler(MessageHandler(user_filters & ~filters.COMMAND, forward_message_to_owner))
    application.add_handler(
        MessageHandler(filters.Chat(OWNER_CHAT_ID) & filters.REPLY, forward_reply_to_user)
    )

    logger.info("Starting bot for owner chat %s", OWNER_CHAT_ID)
    application.run_polling()


if __name__ == "__main__":
    main()

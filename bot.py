import html
import logging
from dataclasses import dataclass
from typing import Dict, Optional

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackContext, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BotConfig:
    token: str
    owner_chat_id: int

    def validate(self) -> None:
        if not self.token or self.token == "YOUR_TELEGRAM_BOT_TOKEN":
            raise RuntimeError("Укажите реальный токен бота в переменной config.token")
        if self.owner_chat_id <= 0:
            raise RuntimeError("Укажите корректный chat_id владельца в config.owner_chat_id")


# Заполните реальные значения прямо здесь, как просили
config = BotConfig(token="YOUR_TELEGRAM_BOT_TOKEN", owner_chat_id=0)

# Mapping between forwarded messages (in the owner's chat) and the originating user ids.
FORWARDED_MESSAGE_MAP_KEY = "forwarded_message_map"


def ensure_map(context: ContextTypes.DEFAULT_TYPE) -> Dict[int, int]:
    """Return the shared mapping that links owner's chat messages to user ids."""
    data = context.bot_data.setdefault(FORWARDED_MESSAGE_MAP_KEY, {})
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


def record_forward(mapping: Dict[int, int], sent_message: Optional[Message], source: Message) -> None:
    if sent_message and source.from_user:
        mapping[sent_message.message_id] = source.from_user.id


async def forward_message_to_owner(update: Update, context: CallbackContext) -> None:
    """Forward any user message to the owner chat, preserving media where possible."""
    message = update.effective_message
    if not message or message.chat_id == config.owner_chat_id:
        return

    user_link = build_user_link(message)
    mapping = ensure_map(context)

    header_text = f"Сообщение от {user_link}"
    if get_effective_text(message):
        header_text = f"{header_text}: {html.escape(get_effective_text(message) or '')}"

    sent_message: Optional[Message] = None
    try:
        await context.bot.send_message(
            chat_id=config.owner_chat_id, text=header_text, parse_mode=ParseMode.HTML
        )
        sent_message = await context.bot.copy_message(
            chat_id=config.owner_chat_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
    except Exception:
        sent_message = await context.bot.send_message(
            chat_id=config.owner_chat_id,
            text=header_text,
            parse_mode=ParseMode.HTML,
        )

    record_forward(mapping, sent_message, message)


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

    try:
        await context.bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=config.owner_chat_id,
            message_id=message.message_id,
        )
    except Exception:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=get_effective_text(message) or "Сообщение от владельца",
            parse_mode=ParseMode.HTML,
        )


def main() -> None:
    config.validate()

    application = Application.builder().token(config.token).build()

    user_filters = (~filters.Chat(config.owner_chat_id)) & ~filters.COMMAND & ~filters.StatusUpdate.ALL

    application.add_handler(MessageHandler(user_filters, forward_message_to_owner))
    application.add_handler(
        MessageHandler(filters.Chat(config.owner_chat_id) & filters.REPLY, forward_reply_to_user)
    )

    logger.info("Starting bot for owner chat %s", config.owner_chat_id)
    application.run_polling()


if __name__ == "__main__":
    main()

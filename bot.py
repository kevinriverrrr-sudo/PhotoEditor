"""
Telegram-бот для удаления фона с фотографий через remove.bg API
"""

import asyncio
import logging
from io import BytesIO

import requests
from requests import RequestException
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import database

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class RemoveBgError(Exception):
    """Базовая ошибка remove.bg."""


class RemoveBgNetworkError(RemoveBgError):
    """Ошибка сети при обращении к remove.bg."""


class RemoveBgQuotaError(RemoveBgError):
    """Ошибка превышения лимита remove.bg."""


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Возвращает главное меню с кнопками."""
    keyboard = [
        [InlineKeyboardButton("📷 Удалить фон", callback_data="remove_bg")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def _extract_error_message(response: requests.Response) -> str:
    """Извлекает текст ошибки из ответа remove.bg."""
    try:
        data = response.json()
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            messages = []
            for error in errors:
                title = error.get("title") if isinstance(error, dict) else None
                detail = error.get("detail") if isinstance(error, dict) else None
                parts = [part for part in (title, detail) if part]
                if parts:
                    messages.append(": ".join(parts))
            if messages:
                return "; ".join(messages)
    except ValueError:
        pass
    return response.text


def remove_background_api(photo_bytes: bytes) -> bytes:
    """Удаляет фон с фотографии используя remove.bg API."""
    try:
        response = requests.post(
            config.REMOVE_BG_API_URL,
            headers={"X-Api-Key": config.REMOVE_BG_API_KEY},
            files={"image_file": ("image.png", photo_bytes)},
            data={"size": "auto"},
            timeout=60,
        )
    except RequestException as exc:
        raise RemoveBgNetworkError("Не удалось подключиться к remove.bg") from exc

    if response.status_code == 200:
        return response.content

    error_message = _extract_error_message(response)
    logger.error(
        "remove.bg API error: status=%s, message=%s", response.status_code, error_message
    )

    if response.status_code in {402, 429}:
        raise RemoveBgQuotaError(error_message)

    raise RemoveBgError(error_message)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    user = update.effective_user
    message = update.message

    if not user or not message:
        return

    database.upsert_user(user.id, user.username, user.first_name)

    await message.reply_text(
        config.WELCOME_TEXT,
        reply_markup=get_main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help."""
    message = update.message
    if not message:
        return

    await message.reply_text(
        config.HELP_TEXT,
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(),
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /profile."""
    user = update.effective_user
    message = update.message

    if not user or not message:
        return

    profile = database.get_user_profile(user.id)
    if not profile:
        return

    created_at = profile["created_at"]
    if "T" in created_at:
        created_at = created_at.split("T")[0]

    profile_text = config.PROFILE_TEXT.format(
        user_id=profile["user_id"],
        first_name=profile["first_name"],
        username=f"@{profile['username']}" if profile["username"] != "—" else "—",
        photos_processed=profile["photos_processed"],
        created_at=created_at,
    )

    await message.reply_text(
        profile_text,
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(),
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    user = query.from_user
    if user:
        database.upsert_user(user.id, user.username, user.first_name)

    if query.data == "remove_bg":
        await query.edit_message_text(
            config.SEND_PHOTO_TEXT,
            reply_markup=get_main_menu_keyboard(),
        )
    elif query.data == "profile" and user:
        profile = database.get_user_profile(user.id)
        if profile:
            created_at = profile["created_at"]
            if "T" in created_at:
                created_at = created_at.split("T")[0]

            profile_text = config.PROFILE_TEXT.format(
                user_id=profile["user_id"],
                first_name=profile["first_name"],
                username=f"@{profile['username']}" if profile["username"] != "—" else "—",
                photos_processed=profile["photos_processed"],
                created_at=created_at,
            )

            await query.edit_message_text(
                profile_text,
                parse_mode="HTML",
                reply_markup=get_main_menu_keyboard(),
            )
    elif query.data == "help":
        await query.edit_message_text(
            config.HELP_TEXT,
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard(),
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик получения фото от пользователя."""
    user = update.effective_user
    message = update.message

    if not user or not message or not message.photo:
        return

    database.upsert_user(user.id, user.username, user.first_name)

    processing_message = await message.reply_text(config.PROCESSING_TEXT)

    try:
        photo_file = await message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        loop = asyncio.get_running_loop()
        output_image = await loop.run_in_executor(
            None,
            remove_background_api,
            bytes(photo_bytes),
        )

        output_buffer = BytesIO(output_image)
        output_buffer.name = "removed_background.png"
        output_buffer.seek(0)

        await message.reply_document(
            document=output_buffer,
            filename="removed_background.png",
            caption=config.SUCCESS_TEXT,
        )

        database.increment_photos_processed(user.id)

        await processing_message.delete()

    except RemoveBgQuotaError as exc:
        logger.warning("Remove.bg quota exceeded: %s", exc)
        await processing_message.edit_text(config.LIMIT_ERROR_TEXT)
    except RemoveBgNetworkError as exc:
        logger.error("Network error while connecting to remove.bg: %s", exc)
        await processing_message.edit_text(config.NETWORK_ERROR_TEXT)
    except RemoveBgError as exc:
        logger.error("Remove.bg API returned an error: %s", exc)
        await processing_message.edit_text(config.ERROR_TEXT)
    except Exception as exc:
        logger.exception("Unexpected error while processing photo: %s", exc)
        await processing_message.edit_text(config.ERROR_TEXT)


def main() -> None:
    """Запуск бота."""
    database.init_db()

    application = Application.builder().token(config.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

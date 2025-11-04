"""
Telegram-бот для удаления фона с фотографий
"""

import asyncio
import logging
from io import BytesIO
from typing import Any, Dict

from rembg import remove
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


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Возвращает главное меню с кнопками."""
    keyboard = [
        [InlineKeyboardButton("📷 Удалить фон", callback_data="remove_bg")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    user = update.effective_user
    if user:
        database.upsert_user(user.id, user.username, user.first_name)

        await update.message.reply_text(
            config.WELCOME_TEXT,
            reply_markup=get_main_menu_keyboard(),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help."""
    await update.message.reply_text(
        config.HELP_TEXT,
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(),
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /profile."""
    user = update.effective_user
    if user:
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

            await update.message.reply_text(
                profile_text,
                parse_mode="HTML",
                reply_markup=get_main_menu_keyboard(),
            )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    if user:
        database.upsert_user(user.id, user.username, user.first_name)

    if query.data == "remove_bg":
        await query.edit_message_text(
            config.SEND_PHOTO_TEXT,
            reply_markup=get_main_menu_keyboard(),
        )
    elif query.data == "profile":
        if user:
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
    if not user:
        return

    database.upsert_user(user.id, user.username, user.first_name)

    processing_message = await update.message.reply_text(config.PROCESSING_TEXT)

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        loop = asyncio.get_event_loop()
        output_image = await loop.run_in_executor(None, remove, photo_bytes)

        output_buffer = BytesIO(output_image)

        await update.message.reply_document(
            document=output_buffer,
            filename="removed_background.png",
            caption=config.SUCCESS_TEXT,
        )

        database.increment_photos_processed(user.id)

        await processing_message.delete()

    except Exception as e:
        logger.error(f"Error processing photo: {e}")
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

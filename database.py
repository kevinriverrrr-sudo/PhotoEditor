"""Работа с базой данных SQLite для Telegram-бота"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from config import DATABASE_NAME

DB_PATH = Path(DATABASE_NAME)


def init_db() -> None:
    """Создает таблицы, если они еще не созданы."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                photos_processed INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


@contextmanager
def get_connection():
    """Контекстный менеджер для подключения к БД."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def upsert_user(user_id: int, username: Optional[str], first_name: Optional[str]) -> None:
    """Создает нового пользователя или обновляет данные существующего."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (user_id,),
        )
        exists = cursor.fetchone()

        if exists:
            cursor.execute(
                """
                UPDATE users
                SET username = ?, first_name = ?
                WHERE user_id = ?
                """,
                (username, first_name, user_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO users (user_id, username, first_name, photos_processed, created_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (user_id, username, first_name, datetime.utcnow().isoformat()),
            )
        conn.commit()


def increment_photos_processed(user_id: int) -> None:
    """Увеличивает счетчик обработанных фото для пользователя."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE users
            SET photos_processed = photos_processed + 1
            WHERE user_id = ?
            """,
            (user_id,),
        )
        conn.commit()


def get_user_profile(user_id: int) -> Optional[Dict[str, Optional[str]]]:
    """Возвращает профиль пользователя."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "user_id": row["user_id"],
        "username": row["username"] or "—",
        "first_name": row["first_name"] or "—",
        "photos_processed": row["photos_processed"],
        "created_at": row["created_at"],
    }

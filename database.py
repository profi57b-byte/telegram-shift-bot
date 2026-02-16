import aiosqlite
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_FILE = 'bot_users.db'


class UserDatabase:
    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path

    async def init_db(self):
        """Инициализация БД: создаём таблицы users и user_settings."""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица пользователей
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    is_l15 BOOLEAN,
                    employee_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Таблица настроек
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    remind_before_hour BOOLEAN DEFAULT 0,
                    daily_remind_time TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            ''')
            await db.commit()
            logger.info(f"База данных инициализирована: {self.db_path}")

    async def save_user(self, user_id, username, is_l15, employee_name):
        """Сохранить/обновить пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT INTO users (user_id, username, is_l15, employee_name, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    is_l15 = excluded.is_l15,
                    employee_name = excluded.employee_name,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, username, is_l15, employee_name))
            await db.commit()

    async def get_user(self, user_id):
        """Получить данные пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM users WHERE user_id = ?', (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_employee_name(self, user_id, employee_name):
        """Обновить имя сотрудника."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET employee_name = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
                (employee_name, user_id)
            )
            await db.commit()

    # Методы для работы с настройками
    async def get_user_settings(self, user_id):
        """Получить настройки пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM user_settings WHERE user_id = ?', (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_user_settings(self, user_id, remind_before_hour=None, daily_remind_time=None):
        """Обновить настройки пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            # Проверяем, есть ли запись
            async with db.execute(
                'SELECT 1 FROM user_settings WHERE user_id = ?', (user_id,)
            ) as cursor:
                exists = await cursor.fetchone()

            if exists:
                # Обновляем
                if remind_before_hour is not None:
                    await db.execute(
                        'UPDATE user_settings SET remind_before_hour = ? WHERE user_id = ?',
                        (remind_before_hour, user_id)
                    )
                if daily_remind_time is not None:
                    await db.execute(
                        'UPDATE user_settings SET daily_remind_time = ? WHERE user_id = ?',
                        (daily_remind_time, user_id)
                    )
            else:
                # Вставляем новую
                await db.execute('''
                    INSERT INTO user_settings (user_id, remind_before_hour, daily_remind_time)
                    VALUES (?, ?, ?)
                ''', (user_id,
                      remind_before_hour if remind_before_hour is not None else 0,
                      daily_remind_time))
            await db.commit()

    async def get_all_users_with_settings(self):
        """Получить всех пользователей с их настройками (для фоновой задачи)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('''
                SELECT u.user_id, u.employee_name, s.remind_before_hour, s.daily_remind_time
                FROM users u
                LEFT JOIN user_settings s ON u.user_id = s.user_id
                WHERE u.employee_name IS NOT NULL
            ''') as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
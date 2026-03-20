"""
Модуль контроля доступа к боту (с руководителями)
"""
import aiosqlite
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ACCESS_DB_FILE = 'bot_access.db'
ADMIN_ID = 662128557  # @photon_27


class AccessControl:
    """Класс для управления доступом к боту и руководителями"""

    def __init__(self, db_path=ACCESS_DB_FILE):
        self.db_path = db_path
        self.admin_id = ADMIN_ID

    async def init_db(self):
        """Инициализация базы данных доступа и таблицы руководителей."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Таблица обычного доступа
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS access_list (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        granted_by INTEGER,
                        granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN DEFAULT 1
                    )
                ''')
                # Таблица руководителей
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS directors (
                        user_id INTEGER PRIMARY KEY,
                        added_by INTEGER,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES access_list(user_id) ON DELETE CASCADE
                    )
                ''')
                # Автоматически добавляем админа в access_list (если нет)
                await db.execute('''
                    INSERT OR IGNORE INTO access_list (user_id, username, granted_by, is_active)
                    VALUES (?, 'photon_27', ?, 1)
                ''', (self.admin_id, self.admin_id))
                await db.commit()
                logger.info(f"База данных доступа инициализирована: {self.db_path}")
        except Exception as e:
            logger.error(f"Ошибка инициализации БД доступа: {e}")

    async def check_access(self, user_id: int) -> bool:
        """
        Проверить, есть ли у пользователя доступ (активный доступ или он руководитель).
        """
        # Сначала проверяем активный доступ в access_list
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    'SELECT is_active FROM access_list WHERE user_id = ?',
                    (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row and row[0]:
                        return True
        except Exception as e:
            logger.error(f"Ошибка проверки доступа: {e}")
            return False

        # Если нет активного доступа, проверяем, является ли руководителем
        return await self.is_director(user_id)

    async def is_director(self, user_id: int) -> bool:
        """Проверить, является ли пользователь руководителем."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    'SELECT 1 FROM directors WHERE user_id = ?',
                    (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return row is not None
        except Exception as e:
            logger.error(f"Ошибка проверки руководителя: {e}")
            return False

    async def add_director(self, user_id: int, added_by: int):
        """
        Назначить пользователя руководителем.
        Также автоматически добавляем его в access_list с активным доступом.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Добавляем в access_list, если нет
                await db.execute('''
                    INSERT INTO access_list (user_id, username, granted_by, is_active)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(user_id) DO UPDATE SET
                        is_active = 1
                ''', (user_id, f"user_{user_id}", added_by))
                # Добавляем в directors
                await db.execute('''
                    INSERT OR IGNORE INTO directors (user_id, added_by)
                    VALUES (?, ?)
                ''', (user_id, added_by))
                await db.commit()
                logger.info(f"Руководитель {user_id} назначен пользователем {added_by}")
        except Exception as e:
            logger.error(f"Ошибка назначения руководителя: {e}")

    async def remove_director(self, user_id: int):
        """Снять пользователя с должности руководителя (доступ остаётся, если был)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('DELETE FROM directors WHERE user_id = ?', (user_id,))
                await db.commit()
                logger.info(f"Руководитель {user_id} удалён")
        except Exception as e:
            logger.error(f"Ошибка удаления руководителя: {e}")

    async def grant_access(self, user_id: int, username: str, granted_by: int):
        """Выдать обычный доступ пользователю."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                    INSERT INTO access_list (user_id, username, granted_by, is_active)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(user_id) DO UPDATE SET
                        username = excluded.username,
                        is_active = 1,
                        granted_at = CURRENT_TIMESTAMP
                ''', (user_id, username, granted_by))
                await db.commit()
                logger.info(f"Доступ выдан пользователю {user_id} ({username})")
        except Exception as e:
            logger.error(f"Ошибка выдачи доступа: {e}")

    async def revoke_access(self, user_id: int):
        """Забрать обычный доступ (но руководитель остаётся руководителем)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'UPDATE access_list SET is_active = 0 WHERE user_id = ?',
                    (user_id,)
                )
                await db.commit()
                logger.info(f"Доступ отозван у пользователя {user_id}")
        except Exception as e:
            logger.error(f"Ошибка отзыва доступа: {e}")

    async def get_all_users(self):
        """Получить список всех пользователей с активным доступом (не руководителей отдельно)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    'SELECT * FROM access_list WHERE is_active = 1 ORDER BY granted_at DESC'
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения списка пользователей: {e}")
            return []

    async def get_all_directors(self):
        """Получить список всех руководителей."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    'SELECT d.*, a.username FROM directors d LEFT JOIN access_list a ON d.user_id = a.user_id ORDER BY d.added_at DESC'
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения списка руководителей: {e}")
            return []

    def is_admin(self, user_id: int) -> bool:
        """Проверить, является ли пользователь администратором (главным)."""
        return user_id == self.admin_id

    def get_admin_info(self):
        """Возвращает информацию о главном администраторе."""
        return {
            'id': self.admin_id,
            'mention': '@photon_27'
        }
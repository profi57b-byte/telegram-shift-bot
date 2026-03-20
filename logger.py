"""
Модуль для логирования действий пользователей бота
"""
import logging
from datetime import datetime
from aiogram import Bot
from aiogram.types import Message

logger = logging.getLogger(__name__)


class BotLogger:
    """Класс для отправки логов в Telegram чат"""

    def __init__(self, bot: Bot, chat_id: str):
        self.bot = bot
        self.chat_id = chat_id
        self.enabled = bool(chat_id and chat_id != 'YOUR_LOG_CHAT_ID')

    async def log_action(self, username: str, action: str):
        """
        Отправить лог действия в чат (для обратной совместимости)
        """
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_message = f"[{timestamp}] Пользователь @{username} {action}"

            logger.info(log_message)

            if self.enabled:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"📝 {log_message}"
                )
        except Exception as e:
            logger.error(f"Ошибка при отправке лога: {e}")

    async def log_error(self, username: str, error_text: str):
        """
        Отправить лог ошибки в чат
        """
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_message = f"[{timestamp}] ⚠️ ОШИБКА у @{username}: {error_text}"

            logger.error(log_message)

            if self.enabled:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"🚨 {log_message}"
                )
        except Exception as e:
            logger.error(f"Ошибка при отправке лога ошибки: {e}")

    async def log_incoming_message(self, message: Message, role: str):
        """
        Логирует входящее сообщение пользователя с указанием роли.
        При наличии медиа пересылает оригинал в чат логов.

        Args:
            message: объект сообщения от пользователя
            role: роль пользователя (👑 АДМИН, 🎯 РУКОВОДИТЕЛЬ, 👤 ПОЛЬЗОВАТЕЛЬ)
        """
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            username = message.from_user.username or str(message.from_user.id)
            user_info = f"@{username} (ID: {message.from_user.id})"

            # Определяем тип сообщения и формируем описание
            content = ""
            media_type = None  # флаг наличия медиа для пересылки

            if message.text:
                content = f"📝 Текст: {message.text}"
            elif message.sticker:
                media_type = "sticker"
                emoji = message.sticker.emoji or ""
                content = f"🖼 Стикер {emoji}"
            elif message.photo:
                media_type = "photo"
                content = f"📷 Фото" + (f" с подписью: {message.caption}" if message.caption else "")
            elif message.video:
                media_type = "video"
                content = f"🎥 Видео" + (f": {message.caption}" if message.caption else "")
            elif message.document:
                media_type = "document"
                content = f"📄 Документ: {message.document.file_name}" + (f" ({message.caption})" if message.caption else "")
            elif message.audio:
                media_type = "audio"
                content = f"🎵 Аудио: {message.audio.title or message.audio.file_name}" + (f" ({message.caption})" if message.caption else "")
            elif message.voice:
                media_type = "voice"
                content = f"🎤 Голосовое сообщение"
            elif message.animation:
                media_type = "animation"
                content = f"🖼 GIF" + (f": {message.caption}" if message.caption else "")
            elif message.contact:
                media_type = "contact"
                content = f"📞 Контакт: {message.contact.first_name} {message.contact.last_name or ''}"
            elif message.location:
                media_type = "location"
                content = f"📍 Местоположение: {message.location.latitude}, {message.location.longitude}"
            elif message.poll:
                media_type = "poll"
                content = f"📊 Опрос: {message.poll.question}"
            else:
                content = f"📦 Другое сообщение (тип: {message.content_type})"

            log_line = f"[{timestamp}] {role} {user_info}\n{content}"

            if self.enabled:
                # Отправляем текстовую информацию
                await self.bot.send_message(self.chat_id, log_line)

                # Если есть медиа, пересылаем оригинал
                if media_type:
                    await self.bot.forward_message(
                        chat_id=self.chat_id,
                        from_chat_id=message.chat.id,
                        message_id=message.message_id
                    )
            else:
                logger.info(log_line)

        except Exception as e:
            logger.error(f"Ошибка при логировании входящего сообщения: {e}")
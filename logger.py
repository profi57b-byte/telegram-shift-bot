"""
Модуль для логирования действий пользователей бота
"""
import logging
from datetime import datetime
from aiogram import Bot

logger = logging.getLogger(__name__)


class BotLogger:
    """Класс для отправки логов в Telegram чат"""
    
    def __init__(self, bot: Bot, chat_id: str):
        self.bot = bot
        self.chat_id = chat_id
        self.enabled = bool(chat_id and chat_id != 'YOUR_LOG_CHAT_ID')
    
    async def log_action(self, username: str, action: str):
        """
        Отправить лог действия в чат
        
        Args:
            username: имя пользователя или ID
            action: описание действия
        """
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_message = f"[{timestamp}] Пользователь @{username} {action}"
            
            # Логируем в консоль
            logger.info(log_message)
            
            # Отправляем в Telegram чат, если включено
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
        
        Args:
            username: имя пользователя или ID
            error_text: текст ошибки
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

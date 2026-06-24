#!/usr/bin/env python3
"""
Скрипт запуска Telegram бота для управления графиком L1.5
"""
import os
import sys
import glob
from pathlib import Path
import threading          # <-- ДОБАВЛЕНО для онлайн-парсера
import obras              # <-- ДОБАВЛЕНО для онлайн-парсера

# Загрузка переменных окружения
try:
    from dotenv import load_dotenv

    if Path('.env').exists():
        load_dotenv()
        print("✅ Загружены переменные из .env")
except ImportError:
    print("⚠️ dotenv не установлен, пропускаем загрузку из .env")


# Проверка наличия токена
bot_token = os.getenv('BOT_TOKEN')
if not bot_token:
    print("❌ BOT_TOKEN не задан в переменных окружения!")
    print("📝 Укажите BOT_TOKEN в переменных окружения на хостинге")
    sys.exit(1)


print("✅ Все проверки пройдены")
print("🚀 Запуск бота...")
print("📊 Используется файл:", os.getenv('EXCEL_FILE'))
# --- ЗАПУСК ФОНОВОГО ОБНОВЛЕНИЯ ДАННЫХ ИЗ GOOGLE SHEETS ---
# Поток-демон автоматически завершится, когда основной процесс завершится
obras_thread = threading.Thread(target=obras.main, daemon=True)
obras_thread.start()
print("🔄 Фоновое обновление data.json запущено")
# -----------------------------------------------------------
print("💡 Для остановки нажмите Ctrl+C")
print("-" * 50)

# Запуск бота
from bot import main
import asyncio

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\n⏹ Бот остановлен пользователем")
except Exception as e:
    print(f"\n❌ Ошибка при работе бота: {e}")
    sys.exit(1)
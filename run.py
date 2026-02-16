#!/usr/bin/env python3
"""
Скрипт запуска Telegram бота для управления графиком L1.5
"""
import os
import sys
from pathlib import Path

# Загрузка переменных окружения (опционально, если файл .env есть)
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

# Проверка наличия Excel файла
excel_file = os.getenv('EXCEL_FILE', 'graph.xlsx')
if not Path(excel_file).exists():
    print(f"❌ Excel файл '{excel_file}' не найден!")
    print(f"📝 Поместите файл в текущую директорию или укажите правильный путь")
    sys.exit(1)

print("✅ Все проверки пройдены")
print("🚀 Запуск бота...")
print("📊 Используется файл:", excel_file)
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
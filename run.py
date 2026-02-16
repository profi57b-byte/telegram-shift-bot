#!/usr/bin/env python3
"""
Скрипт запуска Telegram бота для управления графиком L1.5
"""
import os
import sys
from pathlib import Path

# Проверка наличия .env файла
env_file = Path('.env')
if not env_file.exists():
    print("❌ Файл .env не найден!")
    print("📝 Создайте файл .env на основе .env.example:")
    print("   cp .env.example .env")
    print("   Затем отредактируйте .env и укажите BOT_TOKEN")
    sys.exit(1)

# Загрузка переменных окружения
from dotenv import load_dotenv
load_dotenv()

# Проверка наличия токена
bot_token = os.getenv('BOT_TOKEN')
if not bot_token or bot_token == 'your_bot_token_here':
    print("❌ BOT_TOKEN не настроен в файле .env")
    print("📝 Получите токен у @BotFather и укажите его в .env файле")
    sys.exit(1)

# Проверка наличия Excel файла
excel_file = os.getenv('EXCEL_FILE', 'Webcaster__Clients_Support_График_L1_5.xlsx')
if not Path(excel_file).exists():
    print(f"❌ Excel файл '{excel_file}' не найден!")
    print(f"📝 Поместите файл в текущую директорию или укажите правильный путь в .env")
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

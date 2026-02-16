#!/usr/bin/env python3
"""
Скрипт запуска Telegram бота для управления графиком L1.5
"""
import os
import sys
import glob
from pathlib import Path

# Загрузка переменных окружения
try:
    from dotenv import load_dotenv

    if Path('.env').exists():
        load_dotenv()
        print("✅ Загружены переменные из .env")
except ImportError:
    print("⚠️ dotenv не установлен, пропускаем загрузку из .env")


def find_excel_file():
    """Ищет любой Excel файл (.xlsx или .xls) в текущей директории"""
    # Ищем .xlsx файлы
    xlsx_files = glob.glob("*.xlsx")
    # Ищем .xls файлы
    xls_files = glob.glob("*.xls")

    all_excel = xlsx_files + xls_files

    if not all_excel:
        return None

    # Если нашли несколько, выбираем первый
    if len(all_excel) > 1:
        print(f"⚠️ Найдено несколько Excel файлов: {', '.join(all_excel)}")
        print(f"📝 Используем: {all_excel[0]}")

    return all_excel[0]


# Проверка наличия токена
bot_token = os.getenv('BOT_TOKEN')
if not bot_token:
    print("❌ BOT_TOKEN не задан в переменных окружения!")
    print("📝 Укажите BOT_TOKEN в переменных окружения на хостинге")
    sys.exit(1)

# Автоматический поиск Excel файла
excel_file = os.getenv('EXCEL_FILE')
if not excel_file:
    excel_file = find_excel_file()
    if excel_file:
        os.environ['EXCEL_FILE'] = excel_file
        print(f"✅ Автоматически найден файл: {excel_file}")
    else:
        print("❌ Не найден ни один Excel файл (.xlsx или .xls) в текущей директории!")
        sys.exit(1)
else:
    # Проверяем, существует ли указанный файл
    if not Path(excel_file).exists():
        print(f"❌ Указанный Excel файл '{excel_file}' не найден!")
        print("📝 Пробуем найти любой Excel файл...")

        auto_file = find_excel_file()
        if auto_file:
            os.environ['EXCEL_FILE'] = auto_file
            print(f"✅ Используем найденный файл: {auto_file}")
        else:
            sys.exit(1)

print("✅ Все проверки пройдены")
print("🚀 Запуск бота...")
print("📊 Используется файл:", os.getenv('EXCEL_FILE'))
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
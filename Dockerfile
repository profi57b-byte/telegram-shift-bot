FROM python:3.11-slim

# Установка рабочей директории
WORKDIR /app

# Установка зависимостей системы
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода бота
COPY bot.py .
COPY excel_parser.py .
COPY logger.py .
COPY run.py .

# Создание директории для логов
RUN mkdir -p /app/logs

# Запуск бота
CMD ["python", "run.py"]

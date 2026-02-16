FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей системы
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Создаём директории для данных и логов
RUN mkdir -p /app/logs /app/data

# Указываем переменные окружения по умолчанию (можно переопределить при запуске)
ENV EXCEL_FILE=graph.xlsx

# Запускаем бота
CMD ["python", "run.py"]
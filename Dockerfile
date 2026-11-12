FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /bot

# Tesseract — распознать VIN с фото техпаспорта или таблички (витрина → Профиль → VIN)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Бот работает не от root
RUN useradd --create-home botuser && chown -R botuser /bot
USER botuser

# Сначала применяем миграции, потом запускаем бота
CMD ["sh", "-c", "alembic upgrade head && python -m app.main"]

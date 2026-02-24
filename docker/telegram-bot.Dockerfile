FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY telegram_bot /app/telegram_bot

CMD ["python", "telegram_bot/run_bot.py", "--api-base-url", "http://api:8000"]


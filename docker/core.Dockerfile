FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY core /app/core
COPY telegram_bot /app/telegram_bot

EXPOSE 8000

CMD ["python", "core/run_api.py", "--host", "0.0.0.0", "--port", "8000"]


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt

WORKDIR /opt

COPY requirements.txt /opt/lumiq/requirements.txt
RUN pip install --no-cache-dir -r /opt/lumiq/requirements.txt

COPY . /opt/lumiq

CMD ["python", "-m", "lumiq.telegram_bot.run_bot", "--api-base-url", "http://api:8000"]

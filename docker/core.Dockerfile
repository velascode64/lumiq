FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt

WORKDIR /opt

COPY requirements.txt /opt/lumiq/requirements.txt
RUN pip install --no-cache-dir -r /opt/lumiq/requirements.txt

COPY . /opt/lumiq

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "lumiq.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

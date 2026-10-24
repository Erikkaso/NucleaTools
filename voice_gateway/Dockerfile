FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --no-compile -r requirements.txt
COPY app.py ./app.py
USER 10001:10001
EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "300", "--access-logfile", "-", "--error-logfile", "-", "app:app"]

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY . ./whisper_runtime

EXPOSE 8000

CMD ["uvicorn", "whisper_runtime.app:app", "--host", "0.0.0.0", "--port", "8000"]

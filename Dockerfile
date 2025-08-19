FROM python:3.11-slim

# Ortam
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8

WORKDIR /app

# Sistem bağımlılıkları (ffmpeg, CA sertifikaları)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Python bağımlılıkları
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Uygulama kodu
COPY . /app

# Non-root kullanıcı
RUN useradd -m botuser && \
    chown -R botuser:botuser /app
USER botuser

# Çalıştır
CMD ["python", "-u", "bot.py"]

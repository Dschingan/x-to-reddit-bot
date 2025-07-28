# 1. Adım: Base imaj olarak Python 3.11 kullan
FROM python:3.11-slim

# 2. Adım: Çalışma klasörünü ayarla
WORKDIR /app

# 3. Adım: Sisteme ihtiyaç duyulan paketleri kur (ffmpeg gibi)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 4. Adım: Gereksiz cache bırakma
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONUNBUFFERED=1

# 5. Adım: Python bağımlılıklarını yükle
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# 6. Adım: Proje kodlarını kopyala
COPY . /app

# 7. Adım: Konteyner loglarında düzgün görünmesi için unbuffered mod
CMD ["python", "-u", "bot.py"]

# Python 3.10 tabanlı resmi bir Docker imajı kullan
FROM python:3.10-slim

# Çalışma dizinini ayarla
WORKDIR /app

# Sistem bağımlılıklarını kur (ffmpeg dahil)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean

# Gereken tüm dosyaları kapsayıcıya kopyala
COPY . /app

# Pip'i güncelle ve Python bağımlılıklarını yükle
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Railway ortam değişkenleri .env'den gelecektir

# Bot çalıştırma komutu
CMD ["python", "bot.py"]

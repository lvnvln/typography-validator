# Рабочий вариант на стабильной Debian Bookworm
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Tesseract + языки rus/eng, Ghostscript (EPS), системные либы для Pillow/OpenCV-headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    ghostscript \
    libglib2.0-0 libsm6 libxext6 libxrender1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python-зависимости
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Код
COPY . /app

EXPOSE 7860

# В контейнере слушаем на всех интерфейсах и не открываем браузер
ENV SERVER_NAME=0.0.0.0 \
    PORT=7860 \
    INBROWSER=0

CMD ["python", "app.py"]


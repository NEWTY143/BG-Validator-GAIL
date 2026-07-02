FROM python:3.11-slim

# system OCR engine for scanned BGs
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render injects PORT; shell-form CMD expands it
CMD gunicorn app:app --timeout 180 --workers 1 --bind 0.0.0.0:$PORT

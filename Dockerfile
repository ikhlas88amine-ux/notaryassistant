# Image unique reutilisee par les services "api" et "ui" de docker-compose.yml (commande
# differente selon le service). Usage 100% optionnel : le chemin recommande sans Docker est
# decrit dans le README (embedded Qdrant + Ollama installe directement sur la machine).
FROM python:3.11-slim

# Binaires systeme necessaires a l'extraction des .doc anciens (LibreOffice) et a l'OCR des
# PDF scannes (Tesseract, francais + arabe car les dossiers notariaux melangent les deux langues).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-ara \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000 8501

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

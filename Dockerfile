FROM python:3.11-slim

# Evitar prompts interactivos
ENV DEBIAN_FRONTEND=noninteractive

# Dependencias del sistema (OCR + compilar cosas tipo llama_cpp_python)
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    pkg-config \
    curl \
    git \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
  && rm -rf /var/lib/apt/lists/*

# Carpeta de trabajo
WORKDIR /app

# Instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# ---------- ENV de Aegis ----------
# Ojo: en Render probablemente NO podrás cargar el modelo grande,
# pero dejamos las variables para que la app no reviente.
ENV AEGIS_MODEL_PATH=/app/models/wizardcoder-python-7b-v1.0.Q5_K_M.gguf
ENV AEGIS_N_THREADS=4
ENV AEGIS_N_CTX=2048
ENV AEGIS_N_GPU_LAYERS=0
ENV DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/aegis

# Uvicorn escuchando en 0.0.0.0:8000
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

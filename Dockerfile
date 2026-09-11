# 1. Traer un Linux mínimo con Python 3.12 preinstalado
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 2. Instalar utilidades de Linux necesarias para compilar librerías de PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 3. Copiar requirements.txt e instalar dependencias dentro del contenedor
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

# 4. Copiar todo el código de tu proyecto dentro del contenedor
COPY . /app/

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
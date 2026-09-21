# Pinta Ebook - Backend API

API REST para Pinta Ebook, una plataforma web diseñada para la creación, redacción y edición de e-books asistidos por Inteligencia Artificial generativa.

El backend implementa una arquitectura modular y desacoplada con persistencia híbrida:
- PostgreSQL para la gestión transaccional (usuarios, autenticación, metadatos del catálogo y billetera de créditos).
- MongoDB Atlas para el almacenamiento documental (árbol estructurado de capítulos en HTML y auditoría de interacciones con IA).

---

## Stack Tecnológico

- Lenguaje: Python 3.12
- Framework Web: Django 6.0 y Django REST Framework (DRF)
- Bases de Datos:
  - Relacional: PostgreSQL 16 (orquestado vía Docker)
  - Documental: MongoDB Atlas (conectado mediante pymongo)
- Inteligencia Artificial: OpenRouter API (con soporte de modo simulado / mock para desarrollo local)
- Seguridad y Sanitización HTML: nh3 (sanitizador de alto rendimiento basado en Rust)
- Autenticación: JSON Web Tokens (SimpleJWT) y Google OAuth 2.0 / OpenID Connect
- Contenedores y Orquestación: Docker y Docker Compose

---

## Arquitectura del Proyecto

El proyecto organiza sus responsabilidades por capas (Vistas -> Serializadores -> Servicios -> Infraestructura / Persistencia) dentro de aplicaciones modulares:

```text
pintaebook_backend/
|-- apps/
|   |-- accounts/          # Autenticación, usuarios y roles (JWT y Google OAuth)
|   |-- billing/           # Billetera de créditos, transacciones y deducción pesimista
|   |-- ebooks/            # Catálogo, creación asistida, paginación y filtros
|   |-- content/           # Almacenamiento del árbol HTML en MongoDB y concurrencia optimista
|   |-- ai_engine/         # Inferencia puntual, refinamiento de texto y auditoría
|   |-- exporter/          # Exportación multiformato EPUB/PDF (fase posterior)
|   `-- notifications/     # Eventos y notificaciones (fase posterior)
|-- config/                # Configuración global de Django (base, local, prod), URLs y ASGI/WSGI
|-- core/                  # Utilidades compartidas y cliente singleton de MongoDB Atlas
|-- infrastructure/        # Clientes desacoplados de servicios externos (OpenRouter API)
|-- docker-compose.yml     # Orquestación de servicios (web y db)
`-- Dockerfile             # Imagen del entorno de ejecución
```

---

## Despliegue Local con Docker

El entorno de desarrollo se encuentra estandarizado mediante Docker Compose. No es necesario instalar Python ni PostgreSQL en el sistema operativo anfitrión.

### 1. Variables de Entorno

Copiar la plantilla de configuración en la raíz del proyecto:

En Linux o macOS:
```bash
cp .env.example .env
```

En Windows (PowerShell):
```powershell
Copy-Item .env.example .env
```

Configurar las variables requeridas en el archivo `.env`:

```env
DEBUG=True
SECRET_KEY=tu-clave-secreta-de-django

# Base de datos PostgreSQL (Docker)
DB_NAME=pintaebook_db
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=db
DB_PORT=5432

# Autenticación Google OAuth
GOOGLE_CLIENT_ID=tu-google-client-id.apps.googleusercontent.com

# Persistencia NoSQL (MongoDB Atlas)
MONGO_URI=mongodb+srv://<usuario>:<password>@<cluster>.mongodb.net/pintaebook_nosql?retryWrites=true&w=majority
MONGO_DB_NAME=pintaebook_nosql

# Proveedor de Inteligencia Artificial (OpenRouter)
OPENROUTER_API_KEY=sk-or-v1-tu-clave-aqui
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
AI_DEFAULT_MODEL=google/gemma-4-31b-it:free

# Modo simulado para pruebas locales sin consumo de cuota
AI_MOCK_MODE=True
```

### 2. Construir e Iniciar Contenedores

Levantar los servicios en segundo plano:

```bash
docker compose up -d --build
```

El servidor quedará disponible en: `http://localhost:8000/`

### 3. Ejecutar Migraciones

Aplicar el esquema inicial en PostgreSQL:

```bash
docker compose exec web python manage.py migrate
```

### 4. Ejecutar Pruebas Automatizadas

Correr la suite completa de pruebas unitarias y de integración:

```bash
docker compose exec web python manage.py test
```

También es posible ejecutar pruebas sobre aplicaciones específicas:

```bash
docker compose exec web python manage.py test apps.ebooks apps.content apps.billing apps.ai_engine
```

---

## Referencia de la API

Todas las rutas protegidas requieren el encabezado HTTP:
`Authorization: Bearer <access_token>`

### Autenticación y Cuentas (`apps/accounts`)

| Método | Ruta | Descripción | Acceso |
|---|---|---|---|
| POST | `/api/auth/register/` | Registro tradicional de nuevo autor | Público |
| POST | `/api/auth/login/` | Autenticación con credenciales y emisión de tokens JWT | Público |
| POST | `/api/auth/google/` | Autenticación / registro federado mediante Google OAuth | Público |
| POST | `/api/auth/refresh/` | Renovación del token de acceso | Público |
| GET | `/api/auth/me/` | Información del perfil del usuario autenticado | Privado |

### Billetera y Créditos (`apps/billing`)

| Método | Ruta | Descripción | Acceso |
|---|---|---|---|
| GET | `/api/billing/balance/` | Consulta del saldo actual de créditos y fecha de actualización | Privado |

### Catálogo de E-books (`apps/ebooks`)

| Método | Ruta | Descripción | Acceso |
|---|---|---|---|
| GET | `/api/ebooks/` | Catálogo paginado (10/pág) con filtros (`?search=`, `?created_after=`, `?ordering=`) | Privado |
| POST | `/api/ebooks/` | Creación de libro con estructura base asistida por IA (costo: 100 créditos) | Privado |
| GET | `/api/ebooks/<id>/` | Detalle y metadatos de un e-book específico | Privado |
| DELETE | `/api/ebooks/<id>/` | Eliminación coordinada en PostgreSQL y MongoDB | Privado |

### Contenido y Editor (`apps/content`)

| Método | Ruta | Descripción | Acceso |
|---|---|---|---|
| GET | `/api/ebooks/<id>/content/` | Obtención del árbol documental de capítulos y secciones | Privado |
| PATCH | `/api/ebooks/<id>/content/` | Guardado reactivo de contenido HTML y reordenamiento estructural (gratuito) | Privado |

### Motor de Inteligencia Artificial (`apps/ai_engine`)

| Método | Ruta | Descripción | Acceso |
|---|---|---|---|
| POST | `/api/ai/generate/` | Generación y refinamiento puntual de contenido en sección (costo: 10 créditos) | Privado |

---

## Roadmap y Próximas Fases

- Django Channels y Daphne: Transición a servidor ASGI para soportar WebSockets de larga duración.
- Redis: Integración como capa de comunicación (Channel Layer) y cola de tareas en tiempo real.
- Streaming de Inferencia: Emisión progresiva de tokens (efecto máquina de escribir) hacia el cliente web para reducir tiempos de espera percibidos y evitar bloqueos HTTP.
- Exportador (`apps/exporter`): Generación de archivos distribuidos en formatos multiformato (EPUB, PDF).

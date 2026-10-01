# Pinta Ebook - Backend API

API REST + WebSocket para Pinta Ebook, una plataforma web para la creación, redacción y edición de e-books asistidos por Inteligencia Artificial generativa.

El backend implementa una arquitectura modular y desacoplada con persistencia híbrida:
- **PostgreSQL** para la gestión transaccional (usuarios, autenticación, metadatos del catálogo y billetera de créditos).
- **MongoDB Atlas** para el almacenamiento documental (árbol estructurado de capítulos en HTML y auditoría de interacciones con IA).
- **Redis** como Channel Layer para la comunicación en tiempo real a través de WebSockets.

---

## Stack Tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.12 |
| Framework Web | Django 6.0 + Django REST Framework (DRF) |
| Servidor ASGI | Daphne (reemplaza a Gunicorn/WSGI para soporte WebSocket) |
| WebSockets | Django Channels 4.x |
| Channel Layer | channels_redis → Redis 7 |
| Base de datos relacional | PostgreSQL 16 |
| Base de datos documental | MongoDB Atlas (pymongo) |
| Inteligencia Artificial | OpenRouter API (modelo free compatible) |
| Sanitización HTML | nh3 (basado en Rust) |
| Autenticación | SimpleJWT + Google OAuth 2.0 / OpenID Connect |
| Contenedores | Docker + Docker Compose |

---

## Arquitectura del Proyecto

El proyecto organiza sus responsabilidades por capas (Vistas → Serializadores → Servicios → Infraestructura / Persistencia) dentro de aplicaciones modulares:

```text
pintaebook_backend/
|-- apps/
|   |-- accounts/          # Autenticación, usuarios y roles (JWT y Google OAuth)
|   |-- billing/           # Billetera de créditos, transacciones y deducción pesimista
|   |-- ebooks/            # Catálogo, creación asistida, consumers WebSocket y workers
|   |   |-- consumers.py   # EbookProgressConsumer (WebSocket)
|   |   |-- services.py    # Lógica de negocio: _orchestrate_ai_generation, _emit_progress
|   |   `-- routing.py     # Rutas WebSocket
|   |-- content/           # Almacenamiento del árbol HTML en MongoDB y concurrencia optimista
|   |-- ai_engine/         # Inferencia puntual, refinamiento de texto y auditoría
|   |-- exporter/          # Exportación multiformato EPUB/PDF (fase posterior)
|   `-- notifications/     # Eventos y notificaciones (fase posterior)
|-- config/
|   |-- settings/base.py   # Configuración global (incluye CHANNEL_LAYERS con Redis)
|   |-- asgi.py            # Enrutamiento ASGI: HTTP + WebSocket
|   `-- urls.py
|-- core/                  # Utilidades compartidas y cliente singleton de MongoDB Atlas
|-- infrastructure/        # Clientes desacoplados de servicios externos (OpenRouter API)
|-- docker-compose.yml     # Orquestación: web + db + redis
`-- Dockerfile
```

---

## Flujo de Generación de E-books (WebSocket + REST)

La creación de un e-book con IA es un proceso que puede durar entre 30-120 segundos. Para evitar timeouts HTTP (504) y ofrecer feedback en tiempo real, el flujo se desacopló en dos etapas:

```
[Cliente Angular]
     |
     | 1. POST /api/ebooks/   →   Respuesta 201 INMEDIATA con { ebook_id, status: "PROCESSING" }
     |
     | 2. ws://.../ws/ebooks/<ebook_id>/progress/?token=<jwt>
     |        ↓  (eventos JSON secuenciales)
     |   { step:1, progress:20, message: "Validando créditos..." }
     |   { step:2, progress:45, message: "Estructurando tabla de contenidos..." }
     |   { step:3, progress:70, message: "Redactando capítulos..." }   ← IA genera aquí
     |   { step:4, progress:90, message: "Persistiendo en MongoDB..." }
     |   { step:5, progress:100, status:"COMPLETED", credits_available: N }
     |
     | 3. Angular cierra el modal y navega a /editor/<ebook_id>
```

### Componentes involucrados

| Archivo | Responsabilidad |
|---|---|
| `apps/ebooks/views.py` | `EbookViewSet.create()` → crea fila en PostgreSQL y dispara el worker thread |
| `apps/ebooks/services.py` | `_orchestrate_ai_generation()` → ejecuta los 5 pasos en segundo plano |
| `apps/ebooks/services.py` | `_emit_progress()` → emite eventos al grupo Redis del Channel Layer |
| `apps/ebooks/consumers.py` | `EbookProgressConsumer` → consumer WebSocket, valida JWT y propiedad del ebook |
| `apps/ebooks/routing.py` | Mapea la URL `ws/ebooks/<ebook_id>/progress/` al consumer |
| `config/asgi.py` | Enruta WebSocket vs HTTP al consumer o a Django respectivamente |
| `core/ws_auth.py` | Middleware que autentica el JWT desde el query param `?token=` |

### Eventos WebSocket emitidos

```json
// Paso 1 – 20%
{ "type": "progress_update", "step": 1, "progress": 20, "message": "Validando créditos y reservando metadatos..." }

// Paso 2 – 45%
{ "type": "progress_update", "step": 2, "progress": 45, "message": "Estructurando tabla de contenidos con IA..." }

// Paso 3 – 70%
{ "type": "progress_update", "step": 3, "progress": 70, "message": "Redactando capítulos en formato HTML..." }

// Paso 4 – 90%
{ "type": "progress_update", "step": 4, "progress": 90, "message": "Sanitizando texto y persistiendo en MongoDB Atlas..." }

// Paso 5 – 100% (COMPLETADO)
{ "type": "progress_update", "step": 5, "progress": 100, "status": "COMPLETED", "message": "¡Obra finalizada con éxito!", "credits_available": 400 }

// En caso de error
{ "type": "progress_update", "step": 0, "progress": 0, "status": "FAILED", "message": "Error al generar la obra: ...", "error": "..." }
```

### Códigos de cierre WebSocket

| Código | Significado |
|---|---|
| `4001` | Token JWT no provisto, inválido o expirado |
| `4003` | El usuario autenticado no es dueño del e-book ni administrador |
| `1000` | Cierre normal (COMPLETED o FAILED procesados correctamente) |
| `1011` | Error interno del servidor (ver logs de Daphne) |

---

## Configuración Crítica: Redis para WebSockets

> ⚠️ **Importante para el equipo:** La configuración de Redis para Django Channels requiere ajustes específicos para evitar que los sockets se cierren prematuramente durante la generación de contenido con IA.

### ¿Por qué puede fallar?

Cuando el consumer WebSocket espera mensajes de Redis (`await_many_dispatch`), mantiene una conexión TCP abierta hacia Redis. Si esa conexión tiene un socket timeout corto (el default de redis-py es muy agresivo), se cierra con código `1011` antes de que el worker de IA termine de generar el contenido.

### Configuración correcta en `config/settings/base.py`

```python
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [{
                'address': REDIS_URL,          # o (REDIS_HOST, REDIS_PORT)
                'socket_timeout': None,         # ← SIN timeout en lecturas (crítico)
                'socket_keepalive': True,       # ← Keepalive TCP activo
                'socket_connect_timeout': 10,   # ← Solo para el handshake inicial
            }],
            'expiry': 300,    # mensajes viven 5 minutos en la cola
            'capacity': 100,  # buffer de mensajes por grupo
        },
    },
}
```

### Configuración correcta en `docker-compose.yml`

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --timeout 0 --tcp-keepalive 60
  # --timeout 0       → Redis server no cierra conexiones idle
  # --tcp-keepalive 60 → envía keepalives TCP cada 60 segundos
```

> ⚠️ Si se modifica `docker-compose.yml`, se debe recrear el contenedor con `docker compose down && docker compose up -d` (no solo `docker restart`).

---

## Despliegue Local con Docker

### 1. Variables de Entorno

Copiar la plantilla:

```bash
# Linux / macOS
cp .env.example .env

# Windows (PowerShell)
Copy-Item .env.example .env
```

Configurar las variables en `.env`:

```env
DEBUG=True
SECRET_KEY=tu-clave-secreta-de-django

# PostgreSQL (Docker)
DB_NAME=pintaebook_db
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=db
DB_PORT=5432

# MongoDB Atlas
MONGO_URI=mongodb+srv://<usuario>:<password>@<cluster>.mongodb.net/pintaebook_nosql?retryWrites=true&w=majority
MONGO_DB_NAME=pintaebook_nosql

# OpenRouter (IA)
OPENROUTER_API_KEY=sk-or-v1-tu-clave-aqui
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
AI_DEFAULT_MODEL=dots-studio/dots-3-note-preview:free
AI_MOCK_MODE=FALSE

# Google OAuth (opcional)
GOOGLE_CLIENT_ID=tu-google-client-id.apps.googleusercontent.com
```

### 2. Construir e Iniciar Contenedores

```bash
docker compose up -d --build
```

> El servidor ASGI (Daphne) quedará disponible en `http://localhost:8000/`  
> Los WebSockets escuchan en `ws://localhost:8000/ws/`

### 3. Ejecutar Migraciones

```bash
docker compose exec web python manage.py migrate
```

### 4. Verificar WebSocket manualmente (opcional)

```bash
# Instalar wscat si no está disponible
npm install -g wscat

# Conectarse al canal de progreso (reemplazar <ebook_id> y <token>)
wscat -c "ws://localhost:8000/ws/ebooks/<ebook_id>/progress/?token=<access_token>"
```

### 5. Ejecutar Pruebas Automatizadas

```bash
# Suite completa
docker compose exec web python manage.py test

# Por aplicación
docker compose exec web python manage.py test apps.ebooks apps.content apps.billing apps.ai_engine
```

---

## Referencia de la API

Todas las rutas protegidas requieren: `Authorization: Bearer <access_token>`

### Autenticación (`/api/auth/`)

| Método | Ruta | Descripción | Acceso |
|---|---|---|---|
| POST | `/api/auth/register/` | Registro de nuevo autor | Público |
| POST | `/api/auth/login/` | Login con credenciales (retorna JWT) | Público |
| POST | `/api/auth/google/` | Login federado con Google OAuth | Público |
| POST | `/api/auth/refresh/` | Renovar access token | Público |
| GET | `/api/auth/me/` | Perfil del usuario autenticado | Privado |

### Billetera (`/api/billing/`)

| Método | Ruta | Descripción | Acceso |
|---|---|---|---|
| GET | `/api/billing/balance/` | Saldo actual de créditos | Privado |

### E-books REST (`/api/ebooks/`)

| Método | Ruta | Descripción | Costo | Acceso |
|---|---|---|---|---|
| GET | `/api/ebooks/` | Catálogo paginado (`?search=`, `?ordering=`) | Gratis | Privado |
| POST | `/api/ebooks/` | **Crear e-book** → retorna 201 + `ebook_id` de inmediato, procesamiento asíncrono | 100 créditos | Privado |
| GET | `/api/ebooks/<id>/` | Metadatos del e-book | Gratis | Privado |
| DELETE | `/api/ebooks/<id>/` | Eliminar (PostgreSQL + MongoDB) | Gratis | Privado |
| GET | `/api/ebooks/<id>/content/` | Árbol de capítulos y secciones (HTML) | Gratis | Privado |
| PATCH | `/api/ebooks/<id>/content/` | Guardar cambios de secciones | Gratis | Privado |

### WebSocket de Progreso

| Protocolo | URL | Descripción |
|---|---|---|
| WS/WSS | `/ws/ebooks/<ebook_id>/progress/?token=<jwt>` | Canal de progreso en tiempo real para la generación asistida |

### Motor IA (`/api/ai/`)

| Método | Ruta | Descripción | Costo | Acceso |
|---|---|---|---|---|
| POST | `/api/ai/generate/` | Refinar/expandir sección con IA. Responde `generated_html` | 10 créditos | Privado |

#### Payload `/api/ai/generate/`
```json
{
  "ebook_id": "uuid",
  "chapter_id": "uuid",
  "section_id": "uuid",
  "prompt": "texto de instrucción"
}
```

#### Respuesta `/api/ai/generate/`
```json
{
  "ebook_id": "uuid",
  "chapter_id": "uuid",
  "section_id": "uuid",
  "generated_html": "<p>Contenido generado...</p>",
  "tokens_consumed": 312,
  "credits_debited": 10,
  "credits_available": 390
}
```

> ⚠️ El campo es `generated_html`, no `html`. El frontend Angular debe leer `res.generated_html`.

---

## Notas para el Equipo Frontend

1. **Flujo de creación de e-book:** Siempre hacer `POST /api/ebooks/` primero → obtener `ebook_id` → conectar WebSocket inmediatamente.
2. **Token en WebSocket:** El JWT de acceso va como query param `?token=<access_token>` (no en header, ya que los WebSockets nativos del browser no soportan headers personalizados).
3. **Reconexión:** Si el WebSocket cierra con código `1011`, el backend tuvo un error interno. Mostrar mensaje al usuario y ofrecer reintentar.
4. **Campo IA:** La respuesta de `/api/ai/generate/` usa `generated_html` (no `html`). Los créditos actualizados vienen en `credits_available` (no `credits_remaining`).
5. **Estado PROCESSING:** Los e-books recién creados tienen `status: "PROCESSING"`. No intentar abrir el editor hasta recibir el evento `status: "COMPLETED"` por WebSocket.

---

## Roadmap

- [ ] **Exportador** (`apps/exporter`): generación de EPUB y PDF desde el árbol HTML de MongoDB.
- [ ] **Streaming de tokens** (`ai_engine`): efecto máquina de escribir en el editor al refinar secciones.
- [ ] **Notificaciones** (`apps/notifications`): sistema de alertas en tiempo real para eventos del sistema.
- [ ] **Reconexión automática WebSocket**: retry con backoff exponencial en el frontend para casos de red inestable.

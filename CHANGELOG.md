# Changelog - Pinta Ebook Backend

Todos los cambios notables realizados en el proyecto quedan documentados en este archivo.

El formato se basa en los estándares de registro de cambios técnicos organizados por sprint de desarrollo.

---

## Sprint 3 - Facturación de Créditos, Infraestructura de IA y Persistencia Híbrida

### Resumen General

Se diseñó e implementó la arquitectura de persistencia híbrida coordinada (PostgreSQL + MongoDB Atlas) junto al núcleo transaccional de facturación y la orquestación con modelos de lenguaje masivos (LLMs) vía OpenRouter. 

El sistema permite a los autores aprovisionarse automáticamente de saldo promocional de bienvenida, generar libros completos estructurados en HTML desde su creación inicial, consultar su catálogo con paginación y filtros avanzados, guardar y reordenar capítulos de forma reactiva en el editor, y solicitar refinamientos puntuales con IA con débito atómico y auditoría inmutable de tokens.

---

### Cambios e Implementaciones Detalladas

#### 1. Persistencia Documental y Conectividad NoSQL (`core/mongodb.py`)
- **Singleton MongoDB Atlas:** Creación del helper `get_mongo_db()` con pooling de conexiones persistente y timeout preventivo de 5 segundos.
- **Colección `ebook_contents`:** Diseñada para almacenar el árbol jerárquico completo de capítulos y secciones en código HTML sanitizado.
- **Colección `ia_prompt_logs`:** Implementada para auditoría inmutable de interacciones, modelos empleados y métricas de tokens consumidos.

#### 2. Catálogo, Paginación y Creación Asistida (`apps/ebooks`)
- **Modelo `EbookMetadata`:** Mapeado a la tabla relacional `ebook_metadata` en PostgreSQL para registrar el identificador primario (`UUID`), título, descripción y autor (`ForeignKey` con política `ON DELETE RESTRICT`).
- **Generación Asistida en Creación (`POST /api/ebooks/`):** El servicio `create_ebook` comprueba y debita atómicamente 100 créditos en PostgreSQL, orquesta la inferencia del árbol de capítulos con IA y persiste el documento resultante en `ebook_contents` de MongoDB Atlas vinculándolo mediante el `ebook_id`.
- **Rollback Coordinado:** Si la escritura en MongoDB falla, la transacción de PostgreSQL se revierte por completo (`transaction.atomic()`), retornando error `503 Service Unavailable` sin cobro indebido de saldo.
- **Borrado Coordinado:** Eliminación transaccional en PostgreSQL con supresión pasiva en MongoDB capturando contingencias de red para asegurar resiliencia en el cliente.
- **Paginación Automática (`PageNumberPagination`):** Configuración de tamaño de página fijo a 10 registros (`PAGE_SIZE = 10`) retornando metadatos estructurados de navegación (`count`, `next`, `previous`, `results`).
- **Búsqueda Avanzada y Filtros Combinados:** Integración de `SearchFilter` sobre `title` y `description` (`?search=`), ordenamiento dinámico con `OrderingFilter` (`?ordering=`) y filtrado por fecha de creación (`?created_after=`).

#### 3. Estructura del Editor y Auto-guardado (`apps/content`)
- **Recuperación del Árbol (`GET /api/ebooks/<id>/content/`):** Retorna la jerarquía completa de capítulos y secciones para renderizar el editor visual en el frontend.
- **Guardado Reactivo (`PATCH /api/ebooks/<id>/content/`):** Permite actualizar el código HTML de secciones o reordenar capítulos mediante Drag & Drop sin consumo de créditos.
- **Control de Concurrencia Optimista (OCC):** Control atómico por versionado incremental en MongoDB (`version`: `$inc`), con hasta 3 reintentos automáticos ante conflictos de concurrencia y respuesta `409 Conflict` si la colisión persiste.
- **Seguridad contra XSS:** Sanitización exhaustiva del HTML entrante mediante la biblioteca de alto rendimiento `nh3`.

#### 4. Billetera y Control de Saldo (`apps/billing`)
- **Modelo `CreditBalance`:** Tabla relacional `balances_credito` en PostgreSQL vinculada 1 a 1 con el usuario autenticado.
- **Aprovisionamiento de Cortesía:** Señal de Django (`post_save`) sobre `User` para inicializar automáticamente la billetera con 100 créditos de bienvenida tras el registro local o federado con Google OAuth 2.0.
- **Débito Atómico y Concurrente:** `BillingService.deduct_credits` implementa bloqueo pesimista a nivel de fila (`select_for_update`), neutralizando condiciones de carrera y arrojando `402 Payment Required` ante saldo insuficiente.
- **Consulta de Saldo (`GET /api/billing/balance/`):** Endpoint autenticado que retorna los créditos disponibles y fecha de última actualización.

#### 5. Infraestructura de Inferencia de IA (`infrastructure/ai_client.py`)
- **Cliente HTTP Desacoplado:** Centraliza llamadas hacia la API de OpenRouter con gestión de encabezados técnicos (`HTTP-Referer`, `X-Title`), `System Prompt` semántico y límite estricto de espera (`timeout = 30s`).
- **Aislamiento por Modo Simulado (`AI_MOCK_MODE`):** Soporte por variable de entorno y parámetro de inicialización para testing local y desarrollo sin conexión ni consumo de saldo externo.
- **Excepciones Tipadas de DRF:** Mapeo automático de fallas de infraestructura a `503 Service Unavailable` y `504 Gateway Timeout`.

#### 6. Motor Asistido y Auditoría NoSQL (`apps/ai_engine`)
- **Refinamiento Puntual (`POST /api/ai/generate/`):** Endpoint que valida titularidad de la obra, verifica saldo, descuenta 10 créditos, genera el fragmento con IA y actualiza la sección en MongoDB.
- **Auditoría Inmutable (`ia_prompt_logs`):** Registro seguro de `user_id`, `ebook_id`, `provider`, `model`, `prompt` y `tokens_used`, encapsulado con manejo de errores no bloqueante para resiliencia del servicio.

---

### Resumen de Endpoints Disponibles (Sprint 3)

| Método | Endpoint | Descripción | Requiere Autenticación | Paginado | Costo en Créditos |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/billing/balance/` | Consulta de saldo de créditos disponibles | Sí | No | Gratuito (0) |
| `POST` | `/api/ebooks/` | Creación de libro y redacción inicial con IA | Sí | No | 100 créditos |
| `GET` | `/api/ebooks/` | Listado paginado con búsqueda y filtros | Sí | Sí (10/pág) | Gratuito (0) |
| `GET` | `/api/ebooks/<id>/` | Metadatos detallados de un libro | Sí | No | Gratuito (0) |
| `DELETE` | `/api/ebooks/<id>/` | Eliminación coordinada en PostgreSQL y MongoDB | Sí | No | Gratuito (0) |
| `GET` | `/api/ebooks/<id>/content/` | Obtención del árbol completo de capítulos/secciones | Sí | No | Gratuito (0) |
| `PATCH` | `/api/ebooks/<id>/content/` | Auto-guardado de texto u orden de capítulos | Sí | No | Gratuito (0) |
| `POST` | `/api/ai/generate/` | Generación y refinamiento puntual de sección | Sí | No | 10 créditos |

---

### Pruebas Realizadas
- Ejecución integral de la suite de pruebas unitarias y de integración (`apps.ebooks`, `apps.content`, `apps.billing`, `apps.ai_engine`) ejecutadas satisfactoriamente dentro del contenedor Docker.
- Validación de paginación por lotes (`results`, `count`), búsqueda textual compuesta y ordenamiento dinámico.
- Validación de transacciones concurrentes y aislamiento de lecturas en PostgreSQL mediante bloqueos pesimistas.
- Simulación de contingencias y desconexión de red en MongoDB Atlas comprobando la resiliencia en fallbacks y rollbacks.

---

## Sprint 2 - Módulo de Autenticación, Usuarios y Roles

### Resumen General

Se diseñó e implementó la arquitectura base para la gestión de identidades, control de acceso y autenticación en el backend utilizando Django REST Framework y PostgreSQL. El sistema soporta autenticación tradicional basada en credenciales locales y autenticación federada mediante Google, unificando la emisión de sesiones a través de JSON Web Tokens (JWT).

---

### Cambios e Implementaciones Detalladas

#### 1. Modelo de Usuarios y Roles (`apps/accounts`)
- **Custom User Model:** Se implementó el modelo `User` heredando de `AbstractUser`, utilizando `UUID` como clave primaria en lugar de enteros autoincrementales y configurando `email` como identificador único (`USERNAME_FIELD`).
- **Tabla de Roles:** Se creó el modelo `Role` con su respectiva tabla en base de datos y una relación de clave foránea hacia el usuario (`role`). Se añadieron migraciones de datos (*seeds*) para inicializar los roles base del sistema (`admin`, `author`, `reader`).
- **Manager Personalizado:** Se desarrolló `CustomUserManager` para gestionar la normalización del correo electrónico, la creación de usuarios y la asignación del rol por defecto.
- **Seguridad de Contraseñas:** Integración del hashing de contraseñas de Django mediante algoritmos basados en PBKDF2 con SHA-256 (`set_password()`), garantizando que las credenciales nunca se almacenen en texto plano.

#### 2. Autenticación Tradicional con JWT (`SimpleJWT`)
- **Registro de Usuarios (`POST /api/auth/register/`):** Endpoint para la creación de cuentas con validación de fortaleza de contraseñas y detección de correos duplicados mediante `RegisterSerializer`.
- **Inicio de Sesión (`POST /api/auth/login/`):** Endpoint que valida credenciales locales y emite un par de tokens (`access` y `refresh`).
- **Renovación de Sesión (`POST /api/auth/refresh/`):** Endpoint para refrescar el `access_token` cuando este expira, manteniendo la sesión activa sin necesidad de solicitar nuevamente la contraseña.
- **Consulta de Identidad (`GET /api/auth/me/`):** Endpoint protegido mediante permisos de DRF (`IsAuthenticated`) para retornar la información del usuario autenticado a partir del encabezado `Authorization: Bearer <token>`.
- **Capa de Servicios:** Creación de `services.py` para desacoplar la generación y firma matemática de tokens (`generate_tokens()`), reutilizable en múltiples flujos.

#### 3. Autenticación Federada con Google OAuth 2.0 (OpenID Connect)
- **Verificación de Tokens:** Integración de la biblioteca oficial `google-auth` para validar criptográficamente los tokens `id_token` emitidos por los servidores de Google.
- **Endpoint de Autenticación Social (`POST /api/auth/google/`):** Recibe el token enviado desde el cliente, valida su firma contra el `GOOGLE_CLIENT_ID` y extrae los datos del perfil (`email`, `first_name`, `last_name`).
- **Aprovisionamiento Automático:** Si el usuario no existe en PostgreSQL, se crea automáticamente asignándole el rol de autor (`author`) y marcando su contraseña como no utilizable (`set_unusable_password()`). Si ya existe, se recupera su registro.
- **Sesión Unificada:** El servicio retorna los mismos tokens JWT (`access` y `refresh`) que el flujo tradicional, permitiendo que el frontend maneje una única interfaz de sesión.

---

### Resumen de Endpoints Disponibles (Sprint 2)

| Método | Endpoint | Descripción | Requiere Autenticación |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/register/` | Registro de usuario local con contraseña | No |
| `POST` | `/api/auth/login/` | Inicio de sesión con correo y contraseña | No |
| `POST` | `/api/auth/google/` | Inicio de sesión o registro con Google OAuth | No |
| `POST` | `/api/auth/refresh/` | Renovación del access token mediante refresh token | Sí (vía refresh token) |
| `GET` | `/api/auth/me/` | Obtención de los datos del perfil activo | Sí (`Bearer <access_token>`) |

---

### Pruebas Realizadas
- Verificación de códigos de respuesta HTTP (`200`, `201`, `400`, `401`) mediante Django REST Framework `APIClient`.
- Pruebas de integración del flujo de Google OAuth utilizando tokens generados con Google OAuth Playground.
- Validación de restricciones de base de datos, unicidad de correo y asignación de roles en PostgreSQL.

# Changelog - Pinta Ebook Backend

Todos los cambios notables realizados en el proyecto durante el desarrollo del sistema de autenticación y gestión de usuarios quedan documentados en este archivo.

---

## Sprint 2 - Módulo de Autenticación, Usuarios y Roles

### Resumen General
Se diseñó e implementó la arquitectura base para la gestión de identidades, control de acceso y autenticación en el backend utilizando Django REST Framework y PostgreSQL. El sistema soporta autenticación tradicional basada en credenciales locales y autenticación federada mediante Google, unificando la emisión de sesiones a través de JSON Web Tokens (JWT).

---

### Cambios e Implementaciones Detalladas

#### 1. Modelo de Usuarios y Roles (`apps/accounts`)
* **Custom User Model:** Se implementó el modelo `User` heredando de `AbstractUser`, utilizando `UUID` como clave primaria en lugar de enteros autoincrementales y configurando `email` como identificador único (`USERNAME_FIELD`).
* **Tabla de Roles:** Se creó el modelo `Role` con su respectiva tabla en base de datos y una relación de clave foránea hacia el usuario (`role`). Se añadieron migraciones de datos (*seeds*) para inicializar los roles base del sistema (`admin`, `author`, `reader`).
* **Manager Personalizado:** Se desarrolló `CustomUserManager` para gestionar la normalización del correo electrónico, la creación de usuarios y la asignación del rol por defecto.
* **Seguridad de Contraseñas:** Integración del hashing de contraseñas de Django mediante algoritmos basados en PBKDF2 con SHA-256 (`set_password()`), garantizando que las credenciales nunca se almacenen en texto plano.

#### 2. Autenticación Tradicional con JWT (`SimpleJWT`)
* **Registro de Usuarios (`POST /api/auth/register/`):** Endpoint para la creación de cuentas con validación de fortaleza de contraseñas y detección de correos duplicados mediante `RegisterSerializer`.
* **Inicio de Sesión (`POST /api/auth/login/`):** Endpoint que valida credenciales locales y emite un par de tokens (`access` y `refresh`).
* **Renovación de Sesión (`POST /api/auth/refresh/`):** Endpoint para refrescar el `access_token` cuando este expira, manteniendo la sesión activa sin necesidad de solicitar nuevamente la contraseña.
* **Consulta de Identidad (`GET /api/auth/me/`):** Endpoint protegido mediante permisos de DRF (`IsAuthenticated`) para retornar la información del usuario autenticado a partir del encabezado `Authorization: Bearer <token>`.
* **Capa de Servicios:** Creación de `services.py` para desacoplar la generación y firma matemática de tokens (`generate_tokens()`), reutilizable en múltiples flujos.

#### 3. Autenticación Federada con Google OAuth 2.0 (OpenID Connect)
* **Verificación de Tokens:** Integración de la biblioteca oficial `google-auth` para validar criptográficamente los tokens `id_token` emitidos por los servidores de Google.
* **Endpoint de Autenticación Social (`POST /api/auth/google/`):** Recibe el token enviado desde el cliente, valida su firma contra el `GOOGLE_CLIENT_ID` y extrae los datos del perfil (`email`, `first_name`, `last_name`).
* **Aprovisionamiento Automático:** Si el usuario no existe en PostgreSQL, se crea automáticamente asignándole el rol de autor (`author`) y marcando su contraseña como no utilizable (`set_unusable_password()`). Si ya existe, se recupera su registro.
* **Sesión Unificada:** El servicio retorna los mismos tokens JWT (`access` y `refresh`) que el flujo tradicional, permitiendo que el frontend maneje una única interfaz de sesión.

---

### Resumen de Endpoints Disponibles

| Método | Endpoint | Descripción | Requiere Autenticación |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/register/` | Registro de usuario local con contraseña | No |
| `POST` | `/api/auth/login/` | Inicio de sesión con correo y contraseña | No |
| `POST` | `/api/auth/google/` | Inicio de sesión o registro con Google OAuth | No |
| `POST` | `/api/auth/refresh/` | Renovación del access token mediante refresh token | Sí (vía refresh token) |
| `GET` | `/api/auth/me/` | Obtención de los datos del perfil activo | Sí (`Bearer <access_token>`) |

---

### Pruebas Realizadas
* Verificación manual de códigos de respuesta HTTP (`200`, `201`, `400`, `401`) mediante Django REST Framework `APIClient` y Postman.
* Pruebas de integración del flujo de Google OAuth utilizando tokens reales generados con Google OAuth Playground.
* Validación de restricciones de base de datos, unicidad de correo y asignación de roles en PostgreSQL.

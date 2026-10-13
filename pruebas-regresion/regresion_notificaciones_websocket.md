## Prueba de regresión: Notificaciones en tiempo real (`apps/notifications`)

**Fecha:** 13/10/2026 · **Entorno:** local (Docker) · **Rama:** `francisco`
**Resultado:** ✅ Aprobada, sin regresiones

### Qué se verificó

Que agregar el módulo de notificaciones (WebSocket `ws/notifications/` y avisos desde billing y exporter) **no rompe** los flujos existentes.

### 1. Verificaciones automáticas

| Chequeo | Resultado |
|---|---|
| `manage.py check` | ✅ Sin problemas |
| `makemigrations --check` | ✅ Sin migraciones pendientes |
| Suite completa de tests (`manage.py test`) | ✅ **143 / 143 OK** |

Detalle de los módulos tocados: `accounts` 31 · `billing` 55 · `notifications` 15 (nuevos).

### 2. Prueba real de punta a punta (servidor + Redis + sockets abiertos)

| # | Paso | Resultado |
|---|---|---|
| 1 | Registro de usuario | ✅ 201 |
| 2 | Login | ✅ 200 |
| 3 | Perfil (`/auth/me/`) | ✅ 200 |
| 4 | Saldo inicial | ✅ 1000 créditos |
| 5 | Catálogo de paquetes | ✅ 3 paquetes |
| 6 | Historial de compras | ✅ 200, vacío |
| 7 | Conexión WebSocket de notificaciones | ✅ abierto |
| 8 | Crear e-book con IA | ✅ 201 inmediato, `PROCESSING` |
| 9 | WebSocket de progreso | ✅ abierto |
| 10 | Generación con IA (OpenRouter) | ✅ `COMPLETED` en 28 s |
| 11 | Débito de créditos | ✅ 1000 → 900 |
| 12 | Árbol de capítulos y secciones | ✅ 2 capítulos |
| 13 | Edición de una sección (PATCH) | ✅ 200 |
| 14 | Edición persistida | ✅ |
| 15 | Listado con búsqueda | ✅ |
| 16 | Exportación a EPUB | ✅ 200, archivo válido |
| 17 | Notificación `epub_ready` por WebSocket | ✅ recibida |
| 18 | Refinamiento de sección con IA | ✅ 200, 10 créditos |
| 19 | Borrado del e-book (PostgreSQL + MongoDB) | ✅ 204 |
| 20 | Recuperación de contraseña (cuenta inexistente) | ✅ 200 genérico |

**20 / 20 pasos OK.** Los datos de prueba (usuario y e-book) se eliminaron al terminar.

### 3. Seguridad del WebSocket

| Caso | Resultado |
|---|---|
| Conexión sin token | ✅ Rechazada |
| Token inválido | ✅ Rechazada |
| Usuario A no recibe avisos del usuario B | ✅ |
| Varias pestañas del mismo usuario reciben el aviso | ✅ |

### 4. Notificaciones de pagos (verificado con tests automáticos)

| Caso | Resultado |
|---|---|
| Pago aprobado → `credits_purchased` con saldo nuevo | ✅ |
| Webhook repetido → no notifica dos veces | ✅ |
| Pago rechazado → `payment_failed` | ✅ |
| Pago pendiente → no notifica | ✅ |
| Falla de Redis → el pago se acredita igual | ✅ |

### Fuera del alcance de esta prueba

- **Pago real con Mercado Pago y su webhook:** cubierto con tests automáticos (pasarela simulada). Hace falta una compra de prueba real en producción.
- **WebSocket en Render (producción):** se probó solo en local. Conviene verificarlo tras el deploy.
- **Interfaz del front:** el backend emite los avisos; los toasts los implementa el equipo de front.

### Impacto en despliegue

Sin migraciones, sin dependencias nuevas, sin variables nuevas.

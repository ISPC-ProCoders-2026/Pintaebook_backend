# Sprint 3: Facturación de créditos, infraestructura de IA, auditoría en Mongo y generación asistida

## Descripción y Alcance

Este pull request completa las dependencias críticas del flujo de negocio y cierra el core transaccional del Sprint 3:

- Billetera virtual con aprovisionamiento automático de bienvenida para nuevos usuarios.
- Integración de cliente HTTP desacoplado para inferencia con OpenRouter y soporte para modo simulado (*mock*).
- Auditoría inmutable y no bloqueante de prompts y consumo de tokens en MongoDB Atlas.
- Orquestación de generación de e-books con IA desde la creación inicial del libro y endpoint para refinamiento puntual de secciones desde el editor.

---

## Cambios Introducidos

### Módulo de Facturación (`apps/billing`)
- Modelo `CreditBalance` mapeado a la tabla relacional `balances_credito` en PostgreSQL.
- Señal `post_save` sobre `User` para asignar automáticamente 100 créditos promocionales tras el registro local o mediante Google OAuth.
- Servicio `BillingService` con deducción atómica de créditos y bloqueo pesimista (`select_for_update`) para prevenir condiciones de carrera.
- Endpoint `GET /api/billing/balance/` protegido mediante autenticación JWT.

### Infraestructura de IA (`infrastructure/ai_client.py`)
- Cliente HTTP desacoplado para la API de OpenRouter con timeout preventivo de 30 segundos, encabezados técnicos requeridos y excepciones tipadas (`HTTP 503` y `HTTP 504`).
- Soporte para la variable de entorno `AI_MOCK_MODE=True` para desarrollo local y tests automatizados sin consumo de saldo externo ni dependencia de red.

### Motor de IA (`apps/ai_engine`)
- Servicio `log_ia_interaction` para persistir registros de auditoría en la colección `ia_prompt_logs` de MongoDB Atlas.
- Endpoint `POST /api/ai/generate/` para refinamiento o ampliación puntual de secciones dentro del editor (costo: 10 créditos).

### Catálogo y Generación (`apps/ebooks`)
- Actualización de `create_ebook` para orquestar la generación inicial de capítulos en HTML con IA, debitando de forma atómica el saldo base (100 créditos) y guardando el árbol documental en la colección `ebook_contents` de MongoDB.
- Garantía de *rollback* en PostgreSQL si ocurre cualquier fallo de persistencia en MongoDB.

### Configuración Global (`config/`)
- Registro de `apps.billing` y `apps.ai_engine` en `INSTALLED_APPS` (`config/settings/base.py`).
- Exposición de rutas bajo `/api/billing/` y `/api/ai/` (`config/urls.py`).

### Suite de Pruebas
- Cobertura con suites unitarias y de integración para `billing`, `ai_engine`, `ebooks` y `content` (ejecución completa en verde).

---

## Decisiones Técnicas

- **Persistencia híbrida coordinada:** PostgreSQL asegura la integridad transaccional del balance y del catálogo, mientras que MongoDB almacena documentos extensos de contenido y registros de auditoría de solo lectura/escritura.
- **Manejo seguro de caídas:** Si OpenRouter agota el tiempo de espera o falla la red, la transacción relacional se revierte y bajo ninguna circunstancia se descuentan créditos si el contenido no fue persistido.
- **Auditoría resiliente:** La escritura en `ia_prompt_logs` está aislada con captura de `PyMongoError` para no interrumpir el flujo principal del usuario si la base documental experimenta degradación momentánea.
- **Bypass de administrador:** Los usuarios con rol `ADMIN` operan sin descuento de saldo.

---

## Próxima Implementación (Fase 2)

El flujo actual opera de manera sincrónica vía REST (Fase 1). En el siguiente sprint se incorporará la infraestructura en tiempo real mediante:

- **Django Channels y servidor ASGI Daphne:** En reemplazo del arranque WSGI para soportar conexiones persistentes.
- **Redis:** Despliegue en contenedor como Channel Layer para mensajería Pub/Sub.
- **Consumer de WebSocket (`ws://.../generate/`):** Transmisión progresiva de tokens en vivo (*typewriter effect*) hacia el editor en Angular, previniendo caídas por *Gateway Timeout* en libros extensos y sincronizando saldos en tiempo real.

---

## Guía de Pruebas y Verificación

### 1. Reconstruir contenedor de la aplicación
```bash
docker compose up -d --build web
```

### 2. Ejecutar migraciones pendientes
```bash
docker compose exec web python manage.py migrate
```

### 3. Ejecutar suite de pruebas completa
```bash
docker compose exec web python manage.py test apps.ebooks apps.ai_engine apps.billing apps.content
```

### 4. Flujo manual con token JWT
1. `GET /api/billing/balance/`: Verificar la asignación del saldo inicial de bienvenida (100 créditos).
2. `POST /api/ebooks/` (con `title` y `prompt_idea`): Verificar la creación de metadatos en PostgreSQL, generación del árbol en MongoDB y actualización del saldo a 0 créditos.
3. `POST /api/ai/generate/` (con `ebook_id`, `chapter_id`, `section_id` y `prompt`): Verificar respuesta de generación y descuento de 10 créditos (o respuesta `HTTP 402 Payment Required` si el saldo es insuficiente).

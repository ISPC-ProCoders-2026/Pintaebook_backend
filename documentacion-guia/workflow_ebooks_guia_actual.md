# Guía de Integración Frontend: E-books con IA y Progreso en Tiempo Real
### Pinta Ebook — Documentación Técnica (Sprint 3 + Sprint 4 — Estado Actual)

> **Estado:** ✅ Todo el flujo está 100% implementado, probado y en producción local.  
> Esta guía reemplaza las versiones anteriores del documento. No hay pendientes de WebSocket.

---

## Índice

1. [¿Cómo se guarda cada dato? (Arquitectura)](#1-cómo-se-guarda-cada-dato)
2. [Créditos y modelo económico](#2-créditos-y-modelo-económico)
3. [Estructura del contenido en MongoDB](#3-estructura-del-contenido-en-mongodb)
4. [Flujo completo de integración Angular](#4-flujo-completo-de-integración-angular)
   - [A. Consultar saldo](#paso-a-consultar-saldo)
   - [B. Listar e-books](#paso-b-listar-e-books-con-paginación-y-filtros)
   - [C. Crear e-book con WebSocket de progreso](#paso-c-crear-e-book--barra-de-progreso-en-tiempo-real)
   - [D. Abrir el editor](#paso-d-cargar-el-editor)
   - [E. Guardar cambios manuales](#paso-e-guardar-cambios-manuales-gratuito)
   - [F. Asistente IA dentro del editor](#paso-f-asistente-ia-dentro-del-editor)
5. [Referencia rápida de endpoints](#5-referencia-rápida-de-endpoints)
6. [Gotchas y errores conocidos](#6-gotchas-y-errores-conocidos)

---

## 1. ¿Cómo se guarda cada dato?

El sistema usa dos bases de datos con roles distintos:

| Base de datos | Qué guarda | Por qué |
|---|---|---|
| **PostgreSQL** | Usuarios, roles, créditos, metadatos del e-book (título, autor, status) | Transacciones ACID: si el usuario gasta créditos, los números tienen que cuadrar matemáticamente |
| **MongoDB Atlas** | Árbol de capítulos + secciones con HTML, auditoría de prompts de IA | Documentos JSON flexibles, el contenido del libro no cabe bien en tablas rígidas |

**Vínculo entre las dos:** No hay JOIN de SQL. Se conectan únicamente por el `ebook_id` (UUID que nace en PostgreSQL y se guarda como string en MongoDB).

---

## 2. Créditos y Modelo Económico

| Acción | Costo |
|---|---|
| Registro (bienvenida automática) | +100 créditos |
| Crear un e-book completo con IA | −100 créditos |
| Asistir una sección con IA | −10 créditos |
| Edición manual en el editor | Gratis |

**Regla de integridad:** Si el saldo no alcanza, el backend responde `402 Payment Required` **sin llamar a la IA ni crear registros**. Los usuarios con rol `ADMIN` no se les descuenta saldo.

---

## 3. Estructura del Contenido en MongoDB

```
E-book
 └── Capítulos (chapters[])
      └── Secciones (sections[])
           └── HTML enriquecido (html)
```

```json
{
  "ebook_id": "550e8400-e29b-41d4-a716-446655440000",
  "chapters": [
    {
      "id": "c1111111-...",
      "title": "Capítulo 1: Introducción",
      "sections": [
        {
          "id": "s1111111-...",
          "title": "Conceptos base",
          "html": "<p>El contenido del libro en HTML...</p>"
        }
      ]
    }
  ]
}
```

> ⚠️ **Importante para Angular:** Los IDs de e-books son **UUID (string)**, no números. Nunca tipear como `number`.

---

## 4. Flujo Completo de Integración Angular

**Requisito global:** Todas las rutas (excepto login/register) requieren:
```
Authorization: Bearer <access_token>
```

---

### Paso A: Consultar Saldo

```
GET /api/billing/balance/
```

**Respuesta 200:**
```json
{
  "credits_available": 90,
  "last_updated": "2026-10-01T20:00:00Z"
}
```

Mostrar el saldo en el Navbar o barra de herramientas. Refrescarlo después de cada operación que gaste créditos.

---

### Paso B: Listar E-books con Paginación y Filtros

```
GET /api/ebooks/
```

**Parámetros opcionales:**

| Parámetro | Ejemplo | Descripción |
|---|---|---|
| `page` | `?page=2` | Página (10 registros fijos por página) |
| `search` | `?search=nutricion` | Busca en título y descripción (case-insensitive) |
| `created_after` | `?created_after=2026-09-01` | Filtro por fecha de creación |
| `ordering` | `?ordering=-created_at` | Orden: `title`, `created_at`, `-created_at` |

**Ejemplo combinado:**
```
GET /api/ebooks/?search=salud&ordering=-created_at&page=1
```

**Respuesta 200:**
```json
{
  "count": 25,
  "next": "http://localhost:8000/api/ebooks/?page=2",
  "previous": null,
  "results": [
    {
      "ebook_id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "Guía de Nutrición Deportiva",
      "description": "Manual para deportistas.",
      "status": "COMPLETED",
      "created_at": "2026-10-01T22:00:00Z",
      "updated_at": "2026-10-01T22:00:00Z"
    }
  ]
}
```

> El campo `status` puede ser `PROCESSING`, `COMPLETED` o `FAILED`. No navegar al editor si el status es `PROCESSING`.

---

### Paso C: Crear E-book + Barra de Progreso en Tiempo Real

Este es el flujo más complejo. Funciona en **3 momentos** gracias a WebSocket:

```
[Angular: Modal "Crear libro"]
        │
        │ 1. POST /api/ebooks/
        ▼
[Backend] ──► Crea fila en PostgreSQL con status "PROCESSING"
              Responde 201 INMEDIATAMENTE (sin esperar a la IA)
        │
        │ 2. Angular abre modal de progreso y conecta:
        │    ws://localhost:8000/ws/ebooks/<ebook_id>/progress/?token=<jwt>
        ▼
[Backend: worker thread + Redis]
        ──► event: { step:1, progress:20, message:"Validando créditos..." }
        ──► event: { step:2, progress:45, message:"Estructurando contenidos..." }
        ──► event: { step:3, progress:70, message:"Redactando capítulos..." }  ← IA genera aquí
        ──► event: { step:4, progress:90, message:"Guardando en MongoDB..." }
        ──► event: { step:5, progress:100, status:"COMPLETED", credits_available: N }
        │
        │ 3. Angular cierra el modal y navega a /editor/<ebook_id>
        ▼
[Angular: Editor del e-book]
```

#### C.1 — Petición REST (Paso 1)

```
POST /api/ebooks/
```

**Payload:**
```json
{
  "title": "Guía Práctica de Nutrición Deportiva",
  "description": "Manual básico para atletas.",
  "prompt_idea": "Enfocado en hidratación y balance proteico.",
  "quantity_chapters": 3
}
```

**Respuesta 201 — llega en ~50ms:**
```json
{
  "ebook_id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Guía Práctica de Nutrición Deportiva",
  "description": "Manual básico para atletas.",
  "status": "PROCESSING",
  "created_at": "2026-10-01T20:00:00Z",
  "updated_at": "2026-10-01T20:00:00Z"
}
```

**Error 402 — saldo insuficiente:**
```json
{ "detail": "Créditos insuficientes (20/100) para generar la obra con IA." }
```

#### C.2 — Conexión WebSocket (Paso 2)

Abrir **inmediatamente** después de recibir el 201:

```
ws://localhost:8000/ws/ebooks/<ebook_id>/progress/?token=<access_token>
wss://...                                                                  (producción)
```

> **¿Por qué el token va en la URL?** Los WebSockets nativos del browser no permiten headers personalizados. El backend autentica leyendo el query param `?token=`.

**Códigos de cierre si falla la conexión:**

| Código | Significado | Qué hacer en Angular |
|---|---|---|
| `4001` | Token inválido o expirado | Redirigir al login |
| `4003` | El usuario no es dueño de este e-book | Mostrar error y volver al dashboard |
| `1011` | Error interno del servidor | Mostrar "Intenta nuevamente", el e-book quedó en FAILED |
| `1000` | Cierre normal (completado o fallido correctamente) | Nada, ya se procesó |

#### C.3 — Eventos WebSocket (Paso 3)

El backend emite 5 tramas JSON. **Solo hay que escuchar (`onmessage`), nunca enviar.**

```json
{ "type": "progress_update", "step": 1, "progress": 20,  "message": "Validando créditos y reservando metadatos..." }
{ "type": "progress_update", "step": 2, "progress": 45,  "message": "Estructurando tabla de contenidos con IA..." }
{ "type": "progress_update", "step": 3, "progress": 70,  "message": "Redactando capítulos en formato HTML..." }
{ "type": "progress_update", "step": 4, "progress": 90,  "message": "Sanitizando texto y persistiendo en MongoDB..." }
{ "type": "progress_update", "step": 5, "progress": 100, "status": "COMPLETED", "message": "¡Obra finalizada!", "credits_available": 0 }
```

**Evento de error:**
```json
{
  "type": "progress_update",
  "step": 0,
  "progress": 0,
  "status": "FAILED",
  "message": "Error al generar la obra: OpenRouter timeout...",
  "error": "OpenRouter timeout..."
}
```

> **Nota sobre los pasos 1→2→3:** Los tres primeros eventos llegan casi simultáneamente (la IA no empieza hasta el paso 3). Es normal ver la barra saltar a 70% rápido.

#### C.4 — Implementación en Angular

**`ebook-creation.service.ts`** (implementación de referencia):

```typescript
import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, Subject } from 'rxjs';

export interface ProgressEvent {
  type: 'progress_update';
  step: number;
  progress: number;
  message: string;
  status?: 'PROCESSING' | 'COMPLETED' | 'FAILED';
  credits_available?: number;
  error?: string;
}

export interface CreateEbookResponse {
  ebook_id: string;
  title: string;
  description: string;
  status: 'PROCESSING';
  created_at: string;
  updated_at: string;
}

@Injectable({ providedIn: 'root' })
export class EbookCreationService {
  private readonly http = inject(HttpClient);
  private socket: WebSocket | null = null;
  private progressSubject: Subject<ProgressEvent> | null = null;

  /** Paso 1: disparo REST, retorna casi de inmediato */
  createEbook(payload: {
    title: string;
    description?: string;
    prompt_idea: string;
    quantity_chapters: number;
  }): Observable<CreateEbookResponse> {
    return this.http.post<CreateEbookResponse>('http://localhost:8000/api/ebooks/', payload);
  }

  /** Paso 2: abre WebSocket y expone un Observable de eventos */
  connectToProgress(ebookId: string, token: string): Observable<ProgressEvent> {
    this.disconnect(); // limpia socket anterior si hubiera
    this.progressSubject = new Subject<ProgressEvent>();

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//localhost:8000/ws/ebooks/${ebookId}/progress/?token=${token}`;
    this.socket = new WebSocket(url);

    this.socket.onmessage = (event) => {
      const data: ProgressEvent = JSON.parse(event.data);
      this.progressSubject!.next(data);
      if (data.status === 'COMPLETED' || data.status === 'FAILED') {
        this.disconnect();
      }
    };

    this.socket.onerror = (err) => {
      this.progressSubject!.error(err);
      this.disconnect();
    };

    this.socket.onclose = (event) => {
      if (!this.progressSubject || this.progressSubject.closed) return;

      if (event.code === 4001 || event.code === 4003) {
        this.progressSubject.error(new Error(`Auth error (código ${event.code})`));
        return;
      }
      if (event.code === 1011) {
        this.progressSubject.error(new Error('El servidor cerró la conexión inesperadamente. Intenta nuevamente.'));
        return;
      }
      this.progressSubject.complete();
    };

    return this.progressSubject.asObservable();
  }

  /** Cerrar socket y completar el Observable */
  disconnect(): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.close();
    this.socket = null;
    if (this.progressSubject && !this.progressSubject.closed) this.progressSubject.complete();
    this.progressSubject = null;
  }
}
```

**Lógica en el componente del modal:**

```typescript
onCreateEbook(): void {
  this.ebookCreationService.createEbook(this.form.value).subscribe({
    next: (res) => {
      // Abrir modal de progreso
      this.showProgressModal = true;

      // Conectar WebSocket con el token del localStorage
      const token = localStorage.getItem('access_token') ?? '';
      this.ebookCreationService.connectToProgress(res.ebook_id, token).subscribe({
        next: (event) => {
          this.currentProgress = event.progress;
          this.currentMessage = event.message;

          if (event.status === 'COMPLETED') {
            if (event.credits_available !== undefined) this.balance = event.credits_available;
            setTimeout(() => {
              this.showProgressModal = false;
              this.router.navigate(['/editor', res.ebook_id]);
            }, 800); // pequeña pausa para que el usuario vea el 100%
          }

          if (event.status === 'FAILED') {
            this.showError = true; // mostrar mensaje de error con botón "Cerrar"
          }
        },
        error: (err) => {
          this.showError = true;
          this.errorMessage = err.message ?? 'Error de conexión';
        }
      });
    },
    error: (err) => {
      this.formError = err?.error?.detail ?? 'Error al iniciar la generación';
    }
  });
}

ngOnDestroy(): void {
  this.ebookCreationService.disconnect(); // siempre limpiar al salir del componente
}
```

---

### Paso D: Cargar el Editor

Al entrar a `/editor/:ebook_id`, pedir el árbol de contenido:

```
GET /api/ebooks/<ebook_id>/content/
```

**Respuesta 200:**
```json
{
  "ebook_id": "550e8400-...",
  "chapters": [
    {
      "id": "c1111111-...",
      "title": "Capítulo 1: Introducción",
      "sections": [
        {
          "id": "s1111111-...",
          "title": "Conceptos base",
          "html": "<p>La nutrición deportiva es el pilar del rendimiento...</p>"
        }
      ]
    }
  ]
}
```

Renderizar la sidebar con capítulos y secciones. Al hacer clic en una sección, mostrar su `html` en el área de edición.

---

### Paso E: Guardar Cambios Manuales (Gratuito)

Cuando el usuario edita texto, guardar con debounce (~1 segundo sin tipear):

```
PATCH /api/ebooks/<ebook_id>/content/
```

**Payload — guardar texto de una sección:**
```json
{
  "sections": [
    {
      "chapter_id": "c1111111-...",
      "section_id": "s1111111-...",
      "html": "<p>Texto editado manualmente por el autor.</p>"
    }
  ]
}
```

**Payload — reordenar capítulos (drag & drop):**
```json
{
  "chapters_order": ["c2222222-...", "c1111111-..."]
}
```

**Respuesta 200:**
```json
{
  "ebook_id": "550e8400-...",
  "updated_at": "2026-10-01T22:05:00Z"
}
```

---

### Paso F: Asistente IA dentro del Editor

El usuario escribe un prompt en el panel inferior del editor para ampliar o refinar el contenido de la sección activa.

```
POST /api/ai/generate/
```

**Payload:**
```json
{
  "ebook_id": "550e8400-...",
  "chapter_id": "c1111111-...",
  "section_id": "s1111111-...",
  "prompt": "Escribe una lista de 5 alimentos ricos en magnesio y sus beneficios"
}
```

> 💡 **Tip:** Para que la IA genere contenido coherente con el libro, enriquecer el prompt automáticamente en el frontend antes de enviarlo:
> ```
> Estás editando un e-book.
> Capítulo actual: "Capítulo 1: Nutrición"
> Sección actual: "Conceptos base"
> Contenido existente: "La nutrición deportiva es el pilar..."
> Instrucción del usuario: Escribe una lista de 5 alimentos ricos en magnesio
> ```

**Respuesta 200:**
```json
{
  "ebook_id": "550e8400-...",
  "chapter_id": "c1111111-...",
  "section_id": "s1111111-...",
  "generated_html": "<h3>Fuentes de Magnesio</h3><ul><li>Espinacas...</li></ul>",
  "tokens_consumed": 180,
  "credits_debited": 10,
  "credits_available": 80
}
```

> ⚠️ **El campo es `generated_html`** (no `html`). Los créditos actualizados vienen en `credits_available` (no `credits_remaining`).

**Acción en Angular:** Concatenar `generated_html` al contenido actual de la sección y actualizar el saldo visible con `credits_available`.

---

## 5. Referencia Rápida de Endpoints

| Método | Endpoint | Propósito | Paginado | Costo |
|---|---|---|---|---|
| GET | `/api/billing/balance/` | Consultar saldo | No | Gratis |
| GET | `/api/ebooks/` | Listar biblioteca con filtros | Sí (10/pág) | Gratis |
| POST | `/api/ebooks/` | Crear e-book → responde ebook_id en ~50ms | No | 100 créditos |
| GET | `/api/ebooks/<id>/` | Metadatos del e-book | No | Gratis |
| DELETE | `/api/ebooks/<id>/` | Eliminar (PostgreSQL + MongoDB) | No | Gratis |
| GET | `/api/ebooks/<id>/content/` | Árbol de capítulos y secciones | No | Gratis |
| PATCH | `/api/ebooks/<id>/content/` | Guardar edición manual | No | Gratis |
| POST | `/api/ai/generate/` | Ampliar sección con IA → devuelve `generated_html` | No | 10 créditos |
| **WS** | `/ws/ebooks/<id>/progress/?token=<jwt>` | Canal de progreso en tiempo real | — | — |

---

## 6. Gotchas y Errores Conocidos


### WebSocket cierra con código 1011
Significa que el servidor tuvo un error interno (típicamente un timeout de Redis). El e-book queda en estado `FAILED`. Mostrar mensaje al usuario y ofrecer reintentar.

### Los pasos 1→2→3 llegan casi juntos
Es normal que la barra salte visualmente del 0% al 70% rápido. Los primeros 3 eventos se emiten en milisegundos. La IA tarda en el paso 3 (70%), por eso hay una pausa notable antes del 90%.

### El modelo de IA gratuito puede estar saturado
OpenRouter con modelos `free` puede tener el pool ocupado. Si la generación falla con `FAILED` y el error menciona timeout, simplemente reintentar más tarde. El modelo actual `dots-studio/dots-3-note-preview:free` es el más estable probado.

### Los IDs son UUID (string), no números
Siempre tipar `ebook_id`, `chapter_id`, `section_id` como `string` en TypeScript. Nunca como `number`.

### Los endpoints de Auth son públicos (excepto `/me`)
`/api/auth/register/`, `/api/auth/login/` y `/api/auth/google/` no requieren token. Solo `/api/auth/me/` requiere `Authorization: Bearer`.

### `ngOnDestroy` es obligatorio
Si el usuario navega fuera del dashboard mientras se genera un e-book, el WebSocket queda abierto. Siempre llamar a `ebookCreationService.disconnect()` en `ngOnDestroy()`.

---

*Última actualización: Sprint 4 — 01/10/2026*  

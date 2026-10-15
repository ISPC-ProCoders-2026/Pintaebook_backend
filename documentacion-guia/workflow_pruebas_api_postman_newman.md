# Pruebas de la API con Postman y Newman (AUT-API)

Guía para entender, ejecutar y mantener las pruebas automatizadas de la API de PintaEbook.
Corresponde al **Entregable 3 del Sprint 4** (códigos AUT-API-01 a AUT-API-05).

---

## 1. La idea en 30 segundos

La API se prueba **como una caja negra**: sin mirar el código, solo mandando peticiones HTTP
y verificando lo que responde (código de estado, forma del cuerpo, errores).

| Pieza | Qué es | Dónde está |
|---|---|---|
| **Postman** | Programa con interfaz gráfica para armar y probar peticiones a mano | Se usa para construir y depurar |
| **Colección** | Archivo con todas las peticiones en orden, cada una con sus verificaciones | `tests/api/coleccion.json` |
| **Entorno** | Archivo con las variables (`baseUrl`, `token`, ...) | `tests/api/entorno.local.json` |
| **Newman** | Programa de consola que ejecuta la colección sin abrir Postman | Se instala con npm |
| **Reportes** | Resultado de Newman: uno para personas (HTML) y otro para máquinas (JUnit XML) | `tests/api/reportes/` |

```
Postman (construir y depurar)  ->  exporta coleccion.json  ->  Newman (ejecutar)  ->  reportes HTML y JUnit
```

---

## 2. Las variables: por qué no hay URLs ni tokens escritos a mano

En cada petición se escribe `{{baseUrl}}` en vez de `http://localhost:8000`.
Postman/Newman reemplazan cada `{{variable}}` por su valor del **entorno**.

| Variable | Quién la llena | Para qué sirve |
|---|---|---|
| `baseUrl` | Vos, en el entorno | Dirección del servidor (local o Render) |
| `password` | Vos, en el entorno | Contraseña de los usuarios de prueba |
| `email`, `email2` | Un script (genera uno nuevo por corrida) | Usuarios A y B |
| `token`, `token2` | El script de login/registro | JWT del usuario A y del usuario B |
| `ebookId` | El script de "Crear ebook" | ID del libro, para usarlo en las peticiones siguientes |
| `chapterId`, `sectionId` | El script de "Obtener contenido" | IDs para editar una sección |
| `paqueteId` | El script de "Listar paquetes" | Paquete usado en el checkout |
| `creditsInicial`, `creditsAntesWebhook` | Scripts de saldo | Para comprobar descuentos y que el saldo no cambie |

Para probar contra Render solo se cambia `baseUrl` (hay un `entorno.render.json` de plantilla).

---

## 3. Scripts de test: la parte que "verifica"

Cada petición tiene un script que corre **después** de recibir la respuesta. Hace dos cosas:

**Verificar** (esto es lo que marca ✔ o ✘ en el reporte):

```js
pm.test("Login devuelve 200", () => pm.response.to.have.status(200));
pm.test("access es un string", () => pm.expect(body.access).to.be.a("string"));
```

**Guardar datos para la siguiente petición** (el "encadenado"):

```js
pm.environment.set("token", body.access);
```

Así el login guarda el token y todas las peticiones posteriores lo usan sin copiar nada.

---

## 4. Qué cubre la colección

47 peticiones definidas y 119 verificaciones (Newman puede mostrar unas cuantas más de "requests"
porque la espera de la IA se repite hasta que el libro termina). Se ejecutan en este orden:

| Carpeta | Qué hace | Casos de prueba |
|---|---|---|
| **00 Preparacion** | Registra dos usuarios nuevos (A y B) y lee el saldo inicial | — |
| **01 Auth** | Login correcto e incorrecto, validaciones, `me` con y sin token | TC-API-01, TC-API-02 |
| **02 Ebooks** | **CRUD encadenado**: POST → GET → GET lista → PATCH → PUT, más negativas | TC-API-03, 04, 05, 08 |
| **03 Contenido** | Espera a que la IA termine, lee y edita secciones, negativas | TC-API-06, 07, 08 |
| **04 Billing** | Paquetes, saldo, checkout, historial, webhook con firma falsa | TC-API-09, TC-API-10 |
| **05 Eliminacion** | DELETE del ebook y comprobación de que ya no existe | TC-API-03, 08 |

### Recursos con flujo encadenado

1. **Ebooks**: `POST` (crea y guarda `ebookId`) → `GET` → `PATCH` → `PUT` → … → `DELETE` → `GET` (404).
2. **Contenido del ebook**: espera `COMPLETED` → `GET` → `PATCH` → `GET` (verifica que se guardó).

### Pruebas negativas (por recurso)

| Recurso | Payload inválido → 400 | Sin token → 401 | Otro usuario → 403/404 |
|---|---|---|---|
| Auth | email mal formado, campos faltantes, contraseña corta, email duplicado | `me` | — |
| Ebooks | sin título y `quantity_chapters` fuera de rango | crear, listar, obtener, eliminar | GET, PATCH, DELETE de un ebook ajeno |
| Contenido | body vacío, UUID inválido | GET y PATCH | GET de un ebook ajeno |
| Billing | `paquete_id` no numérico, `estado` inválido | checkout | — |

### Trazabilidad con los casos de prueba

Los IDs son los de la hoja "Test Cases API" de la planilla. `TC-API-01` y `TC-API-02` son la
versión por API de TC-04 y TC-05 (que se probaron manualmente por la interfaz).

| TC | Qué valida | Petición(es) de la colección (carpeta / nombre) | Resultado |
|---|---|---|---|
| TC-API-01 | Login exitoso emite JWT | `01 Auth / TC-API-01 Login exitoso` | Pasa |
| TC-API-02 | Contraseña incorrecta no emite token (401) | `01 Auth / TC-API-02 Login con contraseña incorrecta` | Pasa |
| TC-API-03 | CRUD encadenado de e-book | `02 Ebooks / Crear ... Reemplazar ebook` y `05 Eliminacion / Eliminar ... Verificar eliminación` | Pasa |
| TC-API-04 | Crear e-book con payload inválido (400) | `02 Ebooks / NEG Crear ebook con payload inválido` | Pasa |
| TC-API-05 | Acceso a e-books sin token (401) | `02 Ebooks / NEG ... SIN token` | Pasa |
| TC-API-06 | Leer y editar contenido | `03 Contenido / Obtener contenido` ... `Verificar edición` | Pasa |
| TC-API-07 | Editar contenido con datos inválidos (400) | `03 Contenido / NEG Editar contenido con body vacío` y `... UUID inválido` | Pasa |
| TC-API-08 | Aislamiento entre autores (IDOR) | `NEG TC-API-08 IDOR ...` en carpetas 02, 03 y 05 | Pasa (responde **404**, no revela que el libro existe) |
| TC-API-09 | Webhook sin firma válida no altera saldos | `04 Billing / NEG TC-API-09 ...` y `Saldo sin cambios ...` | **Falla parcial** (ver nota) |
| TC-API-10 | Checkout sin token (401) | `04 Billing / NEG TC-API-10 Checkout SIN token` | Pasa (401) |

> **Nota sobre TC-API-09.** El caso espera rechazo por firma inválida (400, 401 o 403). El backend
> **no valida la cabecera `x-signature`**: su defensa es consultar el pago real a Mercado Pago.
> Con un ID no numérico responde 400; con un ID numérico inexistente responde 404. En ambos casos
> **no se acreditan créditos** (la colección lo comprueba comparando el saldo antes y después).

---

## 5. Cómo ejecutarlo

### Requisitos previos

- **Node.js** LTS (https://nodejs.org).
- Backend levantado (`docker compose up`) en `http://localhost:8000`.
- Internet: el checkout llama a Mercado Pago (credenciales de prueba) y la generación usa OpenRouter.

### Instalar Newman (una sola vez)

```bash
npm install -g newman newman-reporter-htmlextra
```

### Ejecutar

Desde la carpeta del backend (`Pintaebook_backend`):

```bash
newman run tests/api/coleccion.json -e tests/api/entorno.local.json -r cli,htmlextra,junit --reporter-htmlextra-export tests/api/reportes/newman-reporte.html --reporter-junit-export tests/api/reportes/newman-junit.xml
```

Dura unos 20 segundos (espera a que la IA termine de generar el libro de prueba).

### Leer el resultado

- En consola: un ✔ o ✘ por verificación y una tabla final con totales (`failed` debe ser 0).
- `tests/api/reportes/newman-reporte.html`: abrir en el navegador; es el reporte gráfico.
- `tests/api/reportes/newman-junit.xml`: para pipelines de CI.

Para mostrar la evidencia, la captura típica es la tabla final de la consola y la portada del HTML.

---

## 6. Cosas a tener en cuenta

- **Cada corrida crea 2 usuarios nuevos** (`qa.api.<fecha>@test.com`) y gasta 100 créditos del usuario A
  (arranca con 1000 gratis). Por eso se puede ejecutar todas las veces que se quiera.
- **El token dura 5 minutos.** La colección completa tarda ~20 s, no hay problema. Si se corre
  petición por petición a mano en Postman, volver a ejecutar el login si da 401.
- **La carpeta 03 depende de la IA.** Si OpenRouter está caído, el ebook no pasa a `COMPLETED` y
  esa carpeta falla. No es un error de la colección, es información real sobre el sistema.
- **El checkout y el webhook crean/consultan registros en Mercado Pago (modo prueba).** No se mueve dinero.
- Si algo falla con `500` y mensaje sobre barra final, revisar que las URLs terminen en `/`
  (Django con `APPEND_SLASH` rechaza POST sin barra).

---

## 7. Cómo importar todo en Postman (para explorarlo o sacar capturas)

1. Abrir Postman → botón **Import** (arriba a la izquierda).
2. Arrastrar `tests/api/coleccion.json` → **Import**.
3. Volver a **Import** y arrastrar `tests/api/entorno.local.json`.
4. Arriba a la derecha, en el selector de entornos, elegir **PintaEbook - Local**.
5. Para ver un script: abrir una petición → pestaña **Scripts** (o **Tests**).
6. Para correrla completa: click derecho sobre la colección → **Run collection** → **Run**.
   Es el equivalente gráfico de Newman.

---

## 8. Estructura de archivos

```
tests/api/
  coleccion.json           # Colección Postman v2.1
  entorno.local.json       # Variables para localhost
  entorno.render.json      # Plantilla para producción (reemplazar baseUrl)
  reportes/
    newman-reporte.html    # Reporte HTML
    newman-junit.xml       # Reporte JUnit
```

Los archivos de entorno no contienen tokens ni secretos: solo `baseUrl` y la contraseña de un
usuario de prueba que se crea en cada corrida.

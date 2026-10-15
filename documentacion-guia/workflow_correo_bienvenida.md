# Correo de bienvenida

Cuando un usuario se registra, recibe un correo de bienvenida en su casilla.

## Cuándo se envía

| Situación | ¿Envía correo? |
|---|---|
| `POST /api/auth/register/` exitoso (`201`) | Sí |
| Primer ingreso con Google (`POST /api/auth/google/`, usuario nuevo) | Sí |
| Login de un usuario que ya existía | No |
| Registro rechazado (`400`, por ejemplo email duplicado) | No |

## Cómo funciona

- La función es `send_welcome_email(user)` en `apps/accounts/services.py`.
- Usa el **mismo backend de correo que el OTP** (Brevo por API HTTP con `django-anymail`).
  No hay variables de entorno nuevas ni migraciones.
- Es "a prueba de fallos": si Brevo no responde, el error se registra en el log y el
  registro **igual devuelve `201`**. El usuario nunca se queda sin cuenta por un correo.
- El envío es sincrónico, con el timeout de 10 s ya configurado (`EMAIL_TIMEOUT`).

## Contenido

- **Asunto:** `¡Bienvenido/a a Pinta Ebook!`
- **Cuerpo:** saludo con el nombre, confirmación de que la cuenta se creó y una invitación
  a crear su primer e-book. Texto plano, sin enlaces.

## Qué necesita para enviar de verdad

Las mismas variables que el OTP:

```
EMAIL_BACKEND=anymail.backends.brevo.EmailBackend
BREVO_API_KEY=<api key v3 de Brevo>
DEFAULT_FROM_EMAIL=Pinta Ebook <remitente-verificado-en-brevo@gmail.com>
```

Sin `EMAIL_BACKEND`, Django imprime el correo en la consola del contenedor
(`docker compose logs web`), útil para probar en local.

## Qué sabe el front

Nada cambia en la API: la respuesta de registro es la misma. Solo conviene avisar en la
pantalla algo como "Te enviamos un correo de bienvenida" (puede ir a spam).

## Pruebas

`apps/accounts/test_welcome_email.py`:

1. Registro exitoso → llega un correo al email registrado.
2. Registro inválido → no se envía nada.
3. Falla el envío → el registro responde `201` igual.

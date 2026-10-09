"""
Middleware de autenticación para WebSockets mediante SimpleJWT.
Extrae el token del query string (?token=...) y resuelve scope['user'].
Sirve para saber qué usuario se está conectando a través del chat o canal en tiempo real, usando los mismos tokens de inicio de sesión que usa nuestra API de Django Rest Framework (DRF).

El middleware es un componente que se ejecuta automáticamente antes de que cada mensaje WebSocket llegue a la aplicación.
Entonces, este middleware asegura que cualquier conexión WebSocket entrante sea rechazada automáticamente si no trae un token válido de acceso.
Ya que websosket no tiene un header "Authorization", necesitamos extraer el token del query string.

"""
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

User = get_user_model()


@database_sync_to_async
def get_user_from_validated_token(validated_token):
    try:
        user_id = validated_token['user_id']
        return User.objects.get(id=user_id, is_active=True)
    except (User.DoesNotExist, KeyError):
        return AnonymousUser()


class JWTAuthMiddleware:
    """
    Middleware ASGI personalizado para resolver autenticación JWT vía Query String en conexiones WS.
    """
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode('utf-8')
        query_params = parse_qs(query_string)
        token_list = query_params.get('token', None)

        if token_list:
            raw_token = token_list[0]
            try:
                validated_token = AccessToken(raw_token)
                scope['user'] = await get_user_from_validated_token(validated_token)
            except (InvalidToken, TokenError):
                scope['user'] = AnonymousUser()
        else:
            scope['user'] = AnonymousUser()

        return await self.inner(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
"""
Configuración ASGI para el proyecto Pinta Ebook. Enrutador base compatible con Daphne tanto para desarrollo como para despliegues con variable PORT en Railway.
Enruta tráfico HTTP estándar y conexiones WebSocket autenticadas por JWT.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from core.ws_auth import JWTAuthMiddlewareStack
import apps.ebooks.routing


# Lista modular de URLs WebSocket (se extiende en tk056)
websocket_urlpatterns = [
    *apps.ebooks.routing.websocket_urlpatterns,
]

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
})
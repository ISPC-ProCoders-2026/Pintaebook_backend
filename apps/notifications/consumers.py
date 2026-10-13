import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket de notificaciones push del usuario autenticado (ws/notifications/).

    Cada usuario se suscribe al grupo de Redis `user_<id>`: todas sus pestañas
    reciben las mismas alertas. El servidor solo emite; lo que envíe el cliente
    se ignora. Autenticación: JWT en `?token=` (ver core/ws_auth.py).
    """

    async def connect(self):
        user = self.scope.get('user')

        if not user or user.is_anonymous:
            logger.warning('WS notificaciones rechazado: conexión no autenticada')
            await self.close(code=4001)
            return

        self.group_name = f'user_{user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notification_message(self, event):
        """Handler del evento `notification.message` enviado con group_send."""
        await self.send(text_data=json.dumps(event['payload']))

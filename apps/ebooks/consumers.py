import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import EbookMetadata

logger = logging.getLogger(__name__)


class EbookProgressConsumer(AsyncWebsocketConsumer):

    """
    Consumer WebSocket para transmitir eventos de progreso secuencial (Stepped Progress)
    durante la inferencia y armado de un nuevo e-book.

   Se encarga de suscribir el cliente Angular al grupo Redis ebook_progress_<ebook_id>. Valida que el usuario sea el dueño del libro o tenga rol ADMIN. Un consumer es como una view de http
    """

    async def connect(self):
        self.ebook_id = self.scope['url_route']['kwargs'].get('ebook_id')
        self.group_name = f"ebook_progress_{self.ebook_id}"
        self.user = self.scope.get('user')

        # 1. Validar autenticación
        if not self.user or self.user.is_anonymous:
            logger.warning(f"WS Rechazado: Conexión no autenticada para ebook {self.ebook_id}")
            await self.close(code=4001)
            return

        # 2. Validar propiedad de la obra (o rol ADMIN)
        is_owner = await self._is_authorized()
        if not is_owner:
            logger.warning(f"WS Rechazado: Usuario {self.user.id} sin permisos para ebook {self.ebook_id}")
            await self.close(code=4003)
            return

        # 3. Unir conexión al grupo en Redis
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def progress_update(self, event):
        """
        Handler invocado por channel_layer.group_send cuando se emite un evento progress_update.
        """
        payload = {
            "type": "progress_update",
            "step": event.get("step"),
            "progress": event.get("progress"),
            "message": event.get("message"),
        }
        if "status" in event:
            payload["status"] = event["status"]
        if "credits_available" in event:
            payload["credits_available"] = event["credits_available"]
        if "error" in event:
            payload["error"] = event["error"]

        await self.send(text_data=json.dumps(payload))

    @database_sync_to_async
    def _is_authorized(self):
        try:
            ebook = EbookMetadata.objects.get(id=self.ebook_id)
            if hasattr(self.user, 'role') and self.user.role and self.user.role.nombre_rol == 'ADMIN':
                return True
            return ebook.author_id == self.user.id
        except EbookMetadata.DoesNotExist:
            return False
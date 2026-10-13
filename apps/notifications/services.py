import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

LEVELS = ('success', 'info', 'warning', 'error')


def group_name(user_id) -> str:
    return f'user_{user_id}'


def notify_user(user_id, event: str, title: str, message: str,
                level: str = 'info', data: dict | None = None) -> None:
    """
    Envía una notificación push en tiempo real al usuario `user_id`.

    - Si se llama dentro de una transacción de base de datos, el envío se hace
      recién al confirmarla (on_commit): no se avisa de algo que luego se revierte.
    - Nunca levanta excepciones: una notificación fallida no debe romper el flujo
      que la originó (un pago, una exportación).
    - Si el usuario no tiene el WebSocket abierto, la notificación se pierde
      (no se guarda: es solo un aviso en vivo).
    """
    if level not in LEVELS:
        level = 'info'

    payload = {
        'type': 'notification',
        'event': event,
        'level': level,
        'title': title,
        'message': message,
        'data': data or {},
        'timestamp': timezone.now().isoformat(),
    }

    def _send():
        try:
            channel_layer = get_channel_layer()
            if not channel_layer:
                logger.warning('Sin channel layer: se omite la notificación %s', event)
                return
            async_to_sync(channel_layer.group_send)(
                group_name(user_id),
                {'type': 'notification.message', 'payload': payload},
            )
        except Exception as exc:
            logger.warning(
                'No se pudo enviar la notificación %s al usuario %s: %s',
                event, user_id, exc,
            )

    transaction.on_commit(_send)

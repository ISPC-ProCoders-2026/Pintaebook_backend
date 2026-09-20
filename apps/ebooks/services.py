import logging

from django.db import transaction
from django.utils import timezone
from pymongo.errors import PyMongoError
from rest_framework.exceptions import APIException

from core.mongodb import get_mongo_db

from .models import EbookMetadata

logger = logging.getLogger(__name__)

CONTENTS_COLLECTION = 'ebook_contents'


class EbookStorageError(APIException):
    status_code = 503
    default_detail = 'No se pudo completar la operación sobre el contenido del libro. Intentá nuevamente.'
    default_code = 'ebook_storage_unavailable'


def _contents():
    return get_mongo_db()[CONTENTS_COLLECTION]


def create_ebook(*, author, title: str, description: str = '') -> EbookMetadata:
    """
    Crea el libro en PostgreSQL y su documento base en MongoDB.
    Si Mongo falla, la transacción de Postgres se revierte.
    """
    try:
        with transaction.atomic():
            ebook = EbookMetadata.objects.create(
                author=author, title=title, description=description
            )
            now = timezone.now()
            _contents().insert_one({
                '_id': str(ebook.id),
                'chapters': [],
                'created_at': now,
                'updated_at': now,
            })
    except PyMongoError as exc:
        logger.exception('Falló la creación del documento base en Mongo')
        raise EbookStorageError() from exc

    return ebook


def delete_ebook(ebook: EbookMetadata) -> None:
    """
    Borra primero en PostgreSQL (fuente de verdad) y después en MongoDB.
    Si Mongo falla, queda un documento huérfano: se loguea para limpiarlo,
    pero no se le muestra error al usuario porque el libro ya no existe.
    """
    ebook_id = str(ebook.id)  # Django deja pk=None en la instancia tras delete()
    ebook.delete()

    try:
        _contents().delete_one({'_id': ebook_id})
    except PyMongoError:
        logger.exception('Documento huérfano en Mongo tras borrar el libro %s', ebook_id)
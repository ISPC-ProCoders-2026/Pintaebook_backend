import copy
import logging
from datetime import timezone as dt_timezone

import nh3
from django.utils import timezone
from pymongo.errors import PyMongoError
from rest_framework.exceptions import APIException, NotFound, ValidationError

from core.mongodb import get_mongo_db

logger = logging.getLogger(__name__)

CONTENTS_COLLECTION = 'ebook_contents'
MAX_SAVE_ATTEMPTS = 3


class ContentStorageError(APIException):
    status_code = 503
    default_detail = 'No se pudo acceder al contenido del libro. Intentá nuevamente.'
    default_code = 'content_storage_unavailable'


class ContentConflictError(APIException):
    status_code = 409
    default_detail = 'El contenido se modificó al mismo tiempo. Reintentá el guardado.'
    default_code = 'content_conflict'


def _contents():
    return get_mongo_db()[CONTENTS_COLLECTION]


def _as_utc(value):
    """Mongo devuelve datetimes sin zona horaria (siempre en UTC): se la agregamos."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=dt_timezone.utc)
    return value


def sanitize_html(html: str) -> str:
    """Elimina scripts, handlers de eventos y todo lo que no sea HTML seguro."""
    return nh3.clean(html)


def get_content(ebook_id) -> dict:
    """Devuelve el árbol completo de capítulos y secciones."""
    try:
        doc = _contents().find_one({'_id': str(ebook_id)})
    except PyMongoError as exc:
        logger.exception('Falló la lectura del contenido del libro %s', ebook_id)
        raise ContentStorageError() from exc

    if doc is None:
        raise NotFound('El libro no tiene contenido inicializado.')

    return {
        'ebook_id': doc['_id'],
        'chapters': doc.get('chapters', []),
        'updated_at': _as_utc(doc.get('updated_at')),
    }


def _apply_changes(chapters: list, sections: list, chapters_order: list | None) -> list:
    """
    Devuelve una copia de 'chapters' con los cambios aplicados.
    Función pura: no toca Mongo. Si algo es inválido lanza ValidationError
    antes de que exista ninguna escritura (todo o nada).
    """
    chapters = copy.deepcopy(chapters)
    chapters_by_id = {chapter['id']: chapter for chapter in chapters}

    for change in sections:
        chapter_id = str(change['chapter_id'])
        section_id = str(change['section_id'])
        chapter = chapters_by_id.get(chapter_id)
        section = None
        if chapter is not None:
            section = next(
                (s for s in chapter.get('sections', []) if s['id'] == section_id), None
            )
        if section is None:
            raise ValidationError({
                'sections': f'No existe la sección {section_id} en el capítulo {chapter_id}.'
            })
        section['html'] = sanitize_html(change['html'])

    if chapters_order is not None:
        new_order = [str(chapter_id) for chapter_id in chapters_order]
        if sorted(new_order) != sorted(chapters_by_id):
            raise ValidationError({
                'chapters_order': 'Debe contener exactamente los ids de todos los capítulos, sin repetir.'
            })
        chapters = [chapters_by_id[chapter_id] for chapter_id in new_order]

    return chapters


def update_content(ebook_id, *, sections=None, chapters_order=None) -> dict:
    """
    Aplica cambios de HTML y/o orden de capítulos en UNA sola escritura.
    Usa concurrencia optimista: la escritura solo entra si la 'version' del
    documento sigue siendo la que leímos; si no, relee y reintenta.
    """
    key = str(ebook_id)

    for _ in range(MAX_SAVE_ATTEMPTS):
        try:
            doc = _contents().find_one({'_id': key})
            if doc is None:
                raise NotFound('El libro no tiene contenido inicializado.')

            new_chapters = _apply_changes(doc.get('chapters', []), sections or [], chapters_order)
            now = timezone.now()
            version = doc.get('version')  # None si el documento se creó sin versión (tk049)

            result = _contents().update_one(
                {'_id': key, 'version': version},  # version=None también matchea "campo inexistente"
                {
                    '$set': {'chapters': new_chapters, 'updated_at': now},
                    '$inc': {'version': 1},
                },
            )
        except PyMongoError as exc:
            logger.exception('Falló el guardado del contenido del libro %s', key)
            raise ContentStorageError() from exc

        if result.matched_count == 1:
            return {'ebook_id': key, 'updated_at': now}
        # Otro guardado se coló entre nuestra lectura y escritura: releemos y reintentamos.

    raise ContentConflictError()
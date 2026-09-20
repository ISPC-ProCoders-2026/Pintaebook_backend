import json
import logging
import uuid
from django.db import transaction
from django.utils import timezone
from pymongo.errors import PyMongoError
from rest_framework.exceptions import APIException

from core.mongodb import get_mongo_db
from apps.billing.services import BillingService, InsufficientCreditsError
from apps.ai_engine.services import log_ia_interaction
from infrastructure.ai_client import AIClient
from .models import EbookMetadata

logger = logging.getLogger(__name__)

CONTENTS_COLLECTION = 'ebook_contents'
INITIAL_EBOOK_CREDIT_COST = 10


class EbookStorageError(APIException):
    status_code = 503
    default_detail = 'No se pudo completar la operación sobre el contenido del libro. Intentá nuevamente.'
    default_code = 'ebook_storage_unavailable'


def _contents():
    return get_mongo_db()[CONTENTS_COLLECTION]


def _generate_initial_structure(title: str, prompt_idea: str, quantity: int) -> dict:
    """Genera la estructura de capítulos y secciones en HTML mediante IA."""
    ai_client = AIClient()
    consigna = (
        f"Título de la obra: '{title}'.\n"
        f"Idea o temática: '{prompt_idea or title}'.\n"
        f"Cantidad de capítulos requerida: {quantity}.\n\n"
        f"Instrucciones estrictas: Genera una lista JSON que contenga los {quantity} capítulos. "
        f"Cada elemento de la lista debe tener la estructura:\n"
        f'{{"title": "Título del capítulo", "sections": [{{"title": "Subtítulo", "html": "<p>Contenido detallado en HTML...</p>"}}]}}\n'
        f"Responde ÚNICAMENTE el bloque JSON sin etiquetas markdown de bloque (```json)."
    )

    try:
        ai_result = ai_client.generate_content(
            prompt=consigna,
            system_prompt="Eres un editor profesional. Generas árboles de libros exclusivamente en formato JSON válido estructurado.",
        )
        raw_text = ai_result['html'].strip()
        if raw_text.startswith('```'):
            raw_text = raw_text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

        parsed_chapters = json.loads(raw_text)
    except Exception as exc:
        logger.warning("No se pudo parsear la respuesta del modelo, aplicando fallback: %s", exc)
        parsed_chapters = [
            {
                "title": f"Capítulo {i + 1}: Introducción a {title}",
                "sections": [
                    {
                        "title": "Inicio y conceptos base",
                        "html": f"<p>Primeros desarrollos sobre la temática: {prompt_idea or title}.</p>",
                    }
                ],
            }
            for i in range(quantity)
        ]
        ai_result = {
            "tokens_used": 150,
            "provider": "fallback",
            "model": "internal-fallback",
        }

    # Asignar identificadores UUID únicos a cada capítulo y sección
    structured_chapters = []
    for chapter in parsed_chapters:
        ch_id = str(uuid.uuid4())
        sections = []
        for sec in chapter.get('sections', []):
            sections.append({
                'id': str(uuid.uuid4()),
                'title': sec.get('title', 'Sección general'),
                'html': sec.get('html', '<p>Contenido inicial...</p>'),
            })
        structured_chapters.append({
            'id': ch_id,
            'title': chapter.get('title', 'Capítulo sin título'),
            'sections': sections,
        })

    return {
        'chapters': structured_chapters,
        'tokens_used': ai_result.get('tokens_used', 100),
        'provider': ai_result.get('provider', 'openrouter'),
        'model': ai_result.get('model', 'default'),
    }


def create_ebook(
    *,
    author,
    title: str,
    description: str = '',
    prompt_idea: str = '',
    quantity_chapters: int = 3,
) -> EbookMetadata:
    """
    Crea el libro en PostgreSQL y MongoDB, genera su contenido inicial con IA
    y debita el costo inicial de la billetera.
    """
    is_admin = getattr(author, 'role', None) and getattr(author.role, 'nombre_rol', '') == 'ADMIN'
    current_balance = BillingService.get_balance(author)

    if not is_admin and current_balance < INITIAL_EBOOK_CREDIT_COST:
        raise InsufficientCreditsError(
            detail=f"Créditos insuficientes ({current_balance}/{INITIAL_EBOOK_CREDIT_COST}) para generar la obra con IA."
        )

    # Inferencia de contenido antes de persistir
    generation_data = _generate_initial_structure(title, prompt_idea, quantity_chapters)

    try:
        with transaction.atomic():
            ebook = EbookMetadata.objects.create(
                author=author,
                title=title,
                description=description,
            )

            remaining_balance = BillingService.deduct_credits(author, INITIAL_EBOOK_CREDIT_COST)
            ebook.credits_available = remaining_balance

            now = timezone.now()
            _contents().insert_one({
                '_id': str(ebook.id),
                'ebook_id': str(ebook.id),
                'chapters': generation_data['chapters'],
                'version': 1,
                'created_at': now,
                'updated_at': now,
            })
    except PyMongoError as exc:
        logger.exception('Falló la creación del documento en MongoDB')
        raise EbookStorageError() from exc

    # Auditoría no bloqueante
    log_ia_interaction(
        user_id=author.id,
        ebook_id=str(ebook.id),
        provider=generation_data['provider'],
        model=generation_data['model'],
        prompt=prompt_idea or title,
        tokens_used=generation_data['tokens_used'],
    )

    return ebook


def delete_ebook(ebook: EbookMetadata) -> None:
    ebook_id = str(ebook.id)
    ebook.delete()
    try:
        _contents().delete_one({'_id': ebook_id})
    except PyMongoError:
        logger.exception('Documento huérfano en Mongo tras borrar el libro %s', ebook_id)
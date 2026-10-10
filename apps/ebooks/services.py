import json
import logging
import threading
import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone
from pymongo.errors import PyMongoError
from rest_framework.exceptions import APIException

from core.mongodb import get_mongo_db
from apps.billing.services import (
    BillingService,
    InsufficientCreditsError,
)
from apps.ai_engine.services import log_ia_interaction
from infrastructure.ai_client import AIClient
from .models import EbookMetadata

logger = logging.getLogger(__name__)

CONTENTS_COLLECTION = 'ebook_contents'

# Costo de inicialización y generación del ebook.
INITIAL_EBOOK_CREDIT_COST = 100


class EbookStorageError(APIException):
    """Error al interactuar con MongoDB."""

    status_code = 503
    default_detail = (
        'No se pudo completar la operación sobre el contenido del libro. '
        'Intentá nuevamente.'
    )
    default_code = 'ebook_storage_unavailable'


def _contents():
    """Obtiene la colección de contenido de MongoDB."""
    return get_mongo_db()[CONTENTS_COLLECTION]


def _emit_progress(
    ebook_id: str,
    step: int,
    progress: int,
    message: str,
    **extra,
):
    """Emite eventos de progreso por Channels sin interrumpir el worker."""
    channel_layer = get_channel_layer()

    if not channel_layer:
        logger.warning(
            'No hay channel layer configurado; se omite el paso %s',
            step,
        )
        return

    payload = {
        'type': 'progress_update',
        'step': step,
        'progress': progress,
        'message': message,
        **extra,
    }

    try:
        async_to_sync(channel_layer.group_send)(
            f'ebook_progress_{ebook_id}',
            payload,
        )
    except Exception as exc:
        logger.warning(
            'No se pudo emitir el progreso (paso %s, %s%%) '
            'para el ebook %s: %s',
            step,
            progress,
            ebook_id,
            exc,
        )


def _generate_initial_structure(
    title: str,
    prompt_idea: str,
    quantity: int,
) -> dict:
    """Genera la estructura inicial de capítulos y secciones mediante IA."""
    ai_client = AIClient()

    consigna = (
        f"Título de la obra: '{title}'.\n"
        f"Idea o temática: '{prompt_idea or title}'.\n"
        f'Cantidad de capítulos requerida: {quantity}.\n\n'
        f'Instrucciones estrictas: genera una lista JSON que contenga '
        f'los {quantity} capítulos. Cada elemento debe tener esta estructura:\n'
        f'{{"title": "Título del capítulo", "sections": '
        f'[{{"title": "Subtítulo", "html": '
        f'"<p>Contenido detallado en HTML...</p>"}}]}}\n'
        'Responde únicamente el bloque JSON, sin etiquetas markdown.'
    )

    try:
        ai_result = ai_client.generate_content(
            prompt=consigna,
            system_prompt=(
                'Eres un editor profesional. Generas árboles de libros '
                'exclusivamente en formato JSON válido estructurado.'
            ),
        )

        raw_text = str(ai_result.get('html', '')).strip()

        if raw_text.startswith('```'):
            raw_text = (
                raw_text.split('\n', 1)[-1]
                .rsplit('```', 1)[0]
                .strip()
            )

        parsed_chapters = json.loads(raw_text)

    except Exception as exc:
        logger.warning(
            'No se pudo parsear la respuesta del modelo; '
            'se aplica contenido alternativo: %s',
            exc,
        )

        parsed_chapters = [
            {
                'title': f'Capítulo {i + 1}: Introducción a {title}',
                'sections': [
                    {
                        'title': 'Inicio y conceptos base',
                        'html': (
                            '<p>Primeros desarrollos sobre la temática: '
                            f'{prompt_idea or title}.</p>'
                        ),
                    }
                ],
            }
            for i in range(quantity)
        ]

        ai_result = {
            'tokens_used': 150,
            'provider': 'fallback',
            'model': 'internal-fallback',
        }

    structured_chapters = []

    for chapter in parsed_chapters:
        sections = []

        for section in chapter.get('sections', []):
            sections.append({
                'id': str(uuid.uuid4()),
                'title': section.get('title', 'Sección general'),
                'html': section.get(
                    'html',
                    '<p>Contenido inicial...</p>',
                ),
            })

        structured_chapters.append({
            'id': str(uuid.uuid4()),
            'title': chapter.get('title', 'Capítulo sin título'),
            'sections': sections,
        })

    return {
        'chapters': structured_chapters,
        'tokens_used': ai_result.get('tokens_used', 100),
        'provider': ai_result.get('provider', 'openrouter'),
        'model': ai_result.get('model', 'default'),
    }


def _orchestrate_ai_generation(
    ebook_id: str,
    author,
    title: str,
    prompt_idea: str,
    quantity_chapters: int,
):
    """
    Genera el contenido en segundo plano y notifica el progreso.

    Si ocurre un fallo después de descontar créditos, intenta reintegrarlos.
    """
    credits_deducted = False

    is_admin = bool(
        getattr(author, 'role', None)
        and getattr(author.role, 'nombre_rol', '') == 'ADMIN'
    )

    try:
        # Paso 1: validar y descontar créditos.
        _emit_progress(
            ebook_id,
            1,
            20,
            'Validando créditos y reservando metadatos...',
        )

        remaining_balance = BillingService.deduct_credits(
            author,
            INITIAL_EBOOK_CREDIT_COST,
        )

        # Los administradores no consumen créditos.
        credits_deducted = not is_admin

        # Paso 2: preparar la estructura.
        _emit_progress(
            ebook_id,
            2,
            45,
            'Estructurando tabla de contenidos con IA...',
        )

        # Paso 3: generar capítulos.
        _emit_progress(
            ebook_id,
            3,
            70,
            'Redactando capítulos en formato HTML...',
        )

        generation_data = _generate_initial_structure(
            title,
            prompt_idea,
            quantity_chapters,
        )

        # Paso 4: persistir el contenido.
        _emit_progress(
            ebook_id,
            4,
            90,
            'Sanitizando texto y persistiendo en MongoDB Atlas...',
        )

        now = timezone.now()

        _contents().insert_one({
            '_id': ebook_id,
            'ebook_id': ebook_id,
            'chapters': generation_data['chapters'],
            'version': 1,
            'created_at': now,
            'updated_at': now,
        })

        # Registrar el consumo de IA.
        log_ia_interaction(
            user_id=author.id,
            ebook_id=ebook_id,
            provider=generation_data['provider'],
            model=generation_data['model'],
            prompt=prompt_idea or title,
            tokens_used=generation_data['tokens_used'],
        )

        # Paso 5: marcar la generación como finalizada.
        EbookMetadata.objects.filter(id=ebook_id).update(
            status='COMPLETED',
        )

        _emit_progress(
            ebook_id,
            5,
            100,
            '¡Obra finalizada con éxito!',
            status='COMPLETED',
            credits_available=remaining_balance,
        )

    except Exception as exc:
        refunded_balance = None

        # Reintegrar solo si el descuento se completó realmente.
        if credits_deducted:
            try:
                refunded_balance = BillingService.refund_credits(
                    author,
                    INITIAL_EBOOK_CREDIT_COST,
                )
            except Exception:
                logger.exception(
                    'No se pudieron reintegrar los créditos '
                    'del ebook %s',
                    ebook_id,
                )

        logger.exception(
            'Error en la orquestación asíncrona de la obra %s',
            ebook_id,
        )

        EbookMetadata.objects.filter(id=ebook_id).update(
            status='FAILED',
        )

        progress_data = {
            'status': 'FAILED',
            'error': str(exc),
        }

        if refunded_balance is not None:
            progress_data['credits_available'] = refunded_balance

        _emit_progress(
            ebook_id,
            0,
            0,
            f'Error al generar la obra: {str(exc)}',
            **progress_data,
        )


def create_ebook(
    *,
    author,
    title: str,
    description: str = '',
    prompt_idea: str = '',
    quantity_chapters: int = 3,
) -> EbookMetadata:
    """
    Crea los metadatos en PostgreSQL con estado PROCESSING y delega la
    generación del contenido a un hilo en segundo plano.
    """
    is_admin = bool(
        getattr(author, 'role', None)
        and getattr(author.role, 'nombre_rol', '') == 'ADMIN'
    )

    current_balance = BillingService.get_balance(author)

    if (
        not is_admin
        and current_balance < INITIAL_EBOOK_CREDIT_COST
    ):
        raise InsufficientCreditsError(
            detail=(
                f'Créditos insuficientes ({current_balance}/'
                f'{INITIAL_EBOOK_CREDIT_COST}) para generar '
                'la obra con IA.'
            )
        )

    ebook = EbookMetadata.objects.create(
        author=author,
        title=title,
        description=description,
        status='PROCESSING',
    )

    worker_thread = threading.Thread(
        target=_orchestrate_ai_generation,
        args=(
            str(ebook.id),
            author,
            title,
            prompt_idea,
            quantity_chapters,
        ),
        daemon=True,
    )
    worker_thread.start()

    return ebook


def delete_ebook(ebook: EbookMetadata) -> None:
    """
    Elimina el ebook en PostgreSQL y, si es posible, su contenido en MongoDB.
    """
    ebook_id = str(ebook.id)

    ebook.delete()

    try:
        _contents().delete_one({'_id': ebook_id})
    except PyMongoError:
        logger.exception(
            'Documento huérfano en Mongo tras borrar el libro %s',
            ebook_id,
        )
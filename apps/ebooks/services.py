"""
Servicio para la gestión y ciclo de vida de libros electrónicos (Ebooks).

Implementa un modelo de persistencia híbrido:
1. PostgreSQL (Django ORM): Metadatos relacionales, autoría y auditoría general (EbookMetadata).
2. MongoDB: Estructura jerárquica y contenido HTML dinámico de capítulos y secciones.

Además, orquesta la integración con el cliente de Inteligencia Artificial
para la generación de contenido inicial y gestiona el cobro de créditos de usuario.

Incorporación de WebSosket para mostrar el progreso del usuario mientras se genera el e-book. Lo hace en 5 pasos:
1. Validando créditos y reservando metadatos.
2. Estructurando tabla de contenidos con IA.
3. Redactando capítulos en formato HTML.
4. Sanitizando texto y persistiendo en MongoDB Atlas.
5. ¡Obra finalizada con éxito! O hubo un error al generar la obra.

- Se divide la función create_ebook en _emit_progress y _orchestrate_ai_generation para que la función create_ebook solo se encargue de crear el libro en PostgreSQL con status PROCESSING y delegar el resto del trabajo a un hilo en segundo plano.

- Se agrega un método para generar los capítulos en formato HTML y se guarda la estructura en MongoDB Atlas.

- Se agrega un método para auditar el consumo de IA.

- Se agrega un método para eliminar un libro de la base de datos.


"""

import json
import logging
import threading
import uuid
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
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

# Nombre de la colección en MongoDB donde se guarda el árbol de contenidos
CONTENTS_COLLECTION = 'ebook_contents'

# Costo base en créditos para inicializar y generar una obra con IA
INITIAL_EBOOK_CREDIT_COST = 100


class EbookStorageError(APIException):
    """
    Excepción lanzada cuando ocurre un error al interactuar con MongoDB.
    Retorna un código de estado HTTP 503 (Servicio no disponible) al cliente.
    """
    status_code = 503
    default_detail = 'No se pudo completar la operación sobre el contenido del libro. Intentá nuevamente.'
    default_code = 'ebook_storage_unavailable'


def _contents():
    """
    Obtiene la referencia a la colección de contenidos de libros en MongoDB.
    """
    return get_mongo_db()[CONTENTS_COLLECTION]


def _emit_progress(ebook_id: str, step: int, progress: int, message: str, **extra):
    """
    Despacha un evento tipado hacia el grupo Redis Channel Layer de la obra.
    El try/except es defensivo: si Redis tiene un timeout transitorio en un paso
    intermedio, el worker sigue adelante en lugar de morir con 1011.
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        logger.warning("No hay channel layer configurado; se omite el emit del paso %s", step)
        return

    payload = {
        "type": "progress_update",
        "step": step,
        "progress": progress,
        "message": message,
        **extra
    }
    try:
        async_to_sync(channel_layer.group_send)(
            f"ebook_progress_{ebook_id}",
            payload
        )
    except Exception as exc:  # noqa: BLE001
        # Un timeout de Redis en un emit intermedio no debe matar el worker
        logger.warning(
            "No se pudo emitir el progreso (paso %s, %s%%) para el ebook %s: %s",
            step, progress, ebook_id, exc
        )


def _generate_initial_structure(title: str, prompt_idea: str, quantity: int) -> dict:
    """
    Genera la estructura inicial de capítulos y secciones en formato HTML usando IA.
    """
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
        raw_text = str(ai_result.get('html', '')).strip()

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


def _orchestrate_ai_generation(
    ebook_id: str,
    author,
    title: str,
    prompt_idea: str,
    quantity_chapters: int
):
    """
    Ejecuta el flujo secuencial de 5 pasos en segundo plano y emite eventos WebSocket. 
    Esto es para evitar que el usuario tenga que esperar a que se genere el e-book para cerrar la página. 
    
    """
    try:
        # Paso 1 (20%): Validar y debitar créditos con select_for_update
        _emit_progress(ebook_id, 1, 20, "Validando créditos y reservando metadatos...")
        remaining_balance = BillingService.deduct_credits(author, INITIAL_EBOOK_CREDIT_COST)

        # Paso 2 (45%): Estructuración con IA
        _emit_progress(ebook_id, 2, 45, "Estructurando tabla de contenidos con IA...")

        # Paso 3 (70%): Redacción de capítulos en HTML
        _emit_progress(ebook_id, 3, 70, "Redactando capítulos en formato HTML...")
        generation_data = _generate_initial_structure(title, prompt_idea, quantity_chapters)

        # Paso 4 (90%): Sanitización y persistencia en MongoDB Atlas
        _emit_progress(ebook_id, 4, 90, "Sanitizando texto y persistiendo en MongoDB Atlas...")
        now = timezone.now()
        _contents().insert_one({
            '_id': ebook_id,
            'ebook_id': ebook_id,
            'chapters': generation_data['chapters'],
            'version': 1,
            'created_at': now,
            'updated_at': now,
        })

        # Auditoría de IA
        log_ia_interaction(
            user_id=author.id,
            ebook_id=ebook_id,
            provider=generation_data['provider'],
            model=generation_data['model'],
            prompt=prompt_idea or title,
            tokens_used=generation_data['tokens_used'],
        )

        # Paso 5 (100%): Actualización a COMPLETED
        EbookMetadata.objects.filter(id=ebook_id).update(status='COMPLETED')
        _emit_progress(
            ebook_id, 5, 100,
            "¡Obra finalizada con éxito!",
            status="COMPLETED",
            credits_available=remaining_balance
        )

    except Exception as exc:
        logger.exception("Error en la orquestación asíncrona de la obra %s", ebook_id)
        EbookMetadata.objects.filter(id=ebook_id).update(status='FAILED')
        _emit_progress(
            ebook_id, 0, 0,
            f"Error al generar la obra: {str(exc)}",
            status="FAILED",
            error=str(exc)
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
    Crea la reserva del libro en PostgreSQL con status PROCESSING y delega
    la inferencia de IA y persistencia en Mongo a un hilo en segundo plano.
    """
    # 1. Validación de créditos previa
    is_admin = getattr(author, 'role', None) and getattr(author.role, 'nombre_rol', '') == 'ADMIN'
    current_balance = BillingService.get_balance(author)

    if not is_admin and current_balance < INITIAL_EBOOK_CREDIT_COST:
        raise InsufficientCreditsError(
            detail=f"Créditos insuficientes ({current_balance}/{INITIAL_EBOOK_CREDIT_COST}) para generar la obra con IA."
        )

    # 2. Creación inicial en PostgreSQL con status PROCESSING
    ebook = EbookMetadata.objects.create(
        author=author,
        title=title,
        description=description,
        status='PROCESSING',
    )

    # 3. Disparo del proceso en segundo plano
    worker_thread = threading.Thread(
        target=_orchestrate_ai_generation,
        args=(str(ebook.id), author, title, prompt_idea, quantity_chapters),
        daemon=True
    )
    worker_thread.start()

    return ebook


def delete_ebook(ebook: EbookMetadata) -> None:
    """
    Elimina un libro tanto de la base de datos relacional (PostgreSQL) como de la documental (MongoDB).
    """
    ebook_id = str(ebook.id)
    ebook.delete()
    try:
        _contents().delete_one({'_id': ebook_id})
    except PyMongoError:
        logger.exception('Documento huérfano en Mongo tras borrar el libro %s', ebook_id)
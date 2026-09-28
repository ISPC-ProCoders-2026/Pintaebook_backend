"""
Servicio para la gestión y ciclo de vida de libros electrónicos (Ebooks).

Implementa un modelo de persistencia híbrido:
1. PostgreSQL (Django ORM): Metadatos relacionales, autoría y auditoría general (EbookMetadata).
2. MongoDB: Estructura jerárquica y contenido HTML dinámico de capítulos y secciones.

Además, orquesta la integración con el cliente de Inteligencia Artificial
para la generación de contenido inicial y gestiona el cobro de créditos de usuario.
"""

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


def _generate_initial_structure(title: str, prompt_idea: str, quantity: int) -> dict:
    """
    Genera la estructura inicial de capítulos y secciones en formato HTML usando IA.

    Solicita al modelo de lenguaje un árbol de capítulos en formato JSON.
    Si la llamada falla o el modelo devuelve una respuesta que no es JSON válido,
    se aplica un mecanismo de contingencia (fallback) generando capítulos por defecto
    para evitar interrumpir la creación de la obra.

    Args:
        title: Título de la obra.
        prompt_idea: Descripción, temática o sinopsis orientada al modelo.
        quantity: Número de capítulos a generar.

    Returns:
        dict: Estructura que contiene:
            - 'chapters': Lista de capítulos y secciones con identificadores UUID únicos.
            - 'tokens_used': Cantidad de tokens consumidos durante la generación.
            - 'provider': Nombre del proveedor de IA utilizado.
            - 'model': Nombre del modelo específico utilizado.
    """
    ai_client = AIClient()

    # Consigna con restricciones estrictas de salida para facilitar el parseo JSON
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

        # Limpieza defensiva en caso de que el modelo devuelva bloques markdown ```json ... ```
        if raw_text.startswith('```'):
            raw_text = raw_text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

        parsed_chapters = json.loads(raw_text)
    except Exception as exc:
        # Contingencia ante caídas de API o respuestas no parseables:
        # Se crea un esqueleto inicial genérico para permitir que el usuario continúe.
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

    # Normalización del árbol de contenidos asignando identificadores UUID
    # a cada capítulo y sección para poder editarlos de forma granular más adelante.
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
    Crea un nuevo libro electrónico orquestando base de datos relacional, NoSQL y servicios de IA.

    Flujo de ejecución:
    1. Verificación de permisos y créditos disponibles del autor (los usuarios con rol ADMIN están exentos).
    2. Generación asistida por IA de la estructura y contenido base de los capítulos.
    3. Bloque transaccional atómico:
       - Alta del registro de metadatos en PostgreSQL.
       - Débito de los 100 créditos del saldo del autor.
       - Persistencia del contenido estructurado en MongoDB. Si falla la inserción en Mongo,
         se revierte la transacción en PostgreSQL evitando inconsistencias entre ambas bases.
    4. Registro de auditoría del consumo de IA para telemetría y métricas de costos.

    Args:
        author: Instancia del usuario creador (CustomUser).
        title: Título del libro.
        description: Breve descripción o sinopsis general.
        prompt_idea: Indicaciones o temática para guiar al modelo generativo.
        quantity_chapters: Cantidad inicial de capítulos solicitados (por defecto 3).

    Returns:
        EbookMetadata: Instancia del modelo guardado en PostgreSQL con el saldo actualizado.

    Raises:
        InsufficientCreditsError: Si el usuario no es ADMIN y no posee saldo suficiente.
        EbookStorageError: Si ocurre un problema de conexión o inserción en MongoDB.
    """
    # 1. Validación de créditos según rol
    is_admin = getattr(author, 'role', None) and getattr(author.role, 'nombre_rol', '') == 'ADMIN'
    current_balance = BillingService.get_balance(author)

    if not is_admin and current_balance < INITIAL_EBOOK_CREDIT_COST:
        raise InsufficientCreditsError(
            detail=f"Créditos insuficientes ({current_balance}/{INITIAL_EBOOK_CREDIT_COST}) para generar la obra con IA."
        )

    # 2. Generación de capítulos con IA
    generation_data = _generate_initial_structure(title, prompt_idea, quantity_chapters)

    # 3. Persistencia híbrida sincronizada
    try:
        with transaction.atomic():
            # Registro de metadatos en PostgreSQL
            ebook = EbookMetadata.objects.create(
                author=author,
                title=title,
                description=description,
            )

            # Débito de créditos en la billetera del autor
            remaining_balance = BillingService.deduct_credits(author, INITIAL_EBOOK_CREDIT_COST)
            ebook.credits_available = remaining_balance

            # Inserción del documento con capítulos en MongoDB
            # Si esta operación lanza PyMongoError, la transacción de PostgreSQL hace rollback automático
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

    # 4. Registro de auditoría del consumo del modelo generativo
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
    """
    Elimina un libro tanto de la base de datos relacional (PostgreSQL) como de la documental (MongoDB).

    Primero borra el registro relacional y luego remueve el documento asociado en Mongo.
    Si Mongo falla, se captura el error y se registra en logs para identificar posibles
    documentos huérfanos sin interrumpir el flujo.

    Args:
        ebook: Instancia de EbookMetadata que se desea eliminar.
    """
    ebook_id = str(ebook.id)
    ebook.delete()
    try:
        _contents().delete_one({'_id': ebook_id})
    except PyMongoError:
        logger.exception('Documento huérfano en Mongo tras borrar el libro %s', ebook_id)
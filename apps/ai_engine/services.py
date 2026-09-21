import logging
from typing import Any, Dict
from django.utils import timezone
from pymongo.errors import PyMongoError

from core.mongodb import get_mongo_db

logger = logging.getLogger(__name__)

PROMPT_LOGS_COLLECTION = 'ia_prompt_logs'


def _logs_collection():
    return get_mongo_db()[PROMPT_LOGS_COLLECTION]


def log_ia_interaction(
    *,
    user_id: str,
    ebook_id: str,
    provider: str,
    model: str,
    prompt: str,
    tokens_used: int,
    section_id: str = None,
) -> Dict[str, Any]:
    """
    Registra una interacción de IA en MongoDB de forma segura.
    Si la base de datos documental falla al registrar la auditoría,
    se captura la excepción y se loguea una advertencia para evitar
    interrumpir la experiencia del usuario final.
    """
    log_document = {
        'user_id': str(user_id),
        'ebook_id': str(ebook_id),
        'section_id': str(section_id) if section_id else None,
        'provider': provider,
        'model': model,
        'prompt': prompt,
        'tokens_used': tokens_used,
        'created_at': timezone.now(),
    }

    try:
        result = _logs_collection().insert_one(log_document)
        log_document['_id'] = str(result.inserted_id)
        return log_document
    except PyMongoError:
        logger.exception(
            "Fallo no crítico al persistir log de IA en MongoDB para el usuario %s (Ebook: %s)",
            user_id,
            ebook_id,
        )
        return log_document
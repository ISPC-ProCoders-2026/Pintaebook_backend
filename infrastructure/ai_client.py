import json
import logging
import os
import time
from typing import Any, Dict

import requests
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)


class AIServiceUnavailableError(APIException):
    status_code = 503
    default_detail = 'El servicio de Inteligencia Artificial no está disponible. Intente nuevamente más tarde.'
    default_code = 'ai_service_unavailable'


class AITimeoutError(APIException):
    status_code = 504
    default_detail = 'El proveedor de Inteligencia Artificial tardó demasiado en responder (Timeout). No se debitaron créditos.'
    default_code = 'ai_gateway_timeout'


class AIClient:
    """
    Cliente de infraestructura desacoplado para inferencia vía OpenRouter API.
    Aísla las vistas y modelos de los detalles de red y formato de terceros.
    """

    def __init__(self):
        self.api_key = os.getenv('OPENROUTER_API_KEY', '')
        self.base_url = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1').rstrip('/')
        self.default_model = os.getenv('AI_DEFAULT_MODEL', 'google/gemma-4-31b-it:free')
        self.mock_mode = os.getenv('AI_MOCK_MODE', 'False').lower() in ('true', '1', 't')
        self.timeout = 30  # Timeout en segundos

    def generate_content(
        self,
        prompt: str,
        system_prompt: str = '',
        model: str = None,
    ) -> Dict[str, Any]:
        """
        Ejecuta la inferencia y retorna un diccionario normalizado:
        {
            "html": "<p>...</p>",
            "tokens_used": int,
            "provider": str,
            "model": str
        }
        """
        target_model = model or self.default_model

        if self.mock_mode:
            return self._mock_generation(prompt, target_model)

        return self._call_openrouter(prompt, system_prompt, target_model)

    def _mock_generation(self, prompt: str, model: str) -> Dict[str, Any]:
        """
        Respuesta simulada para ejecución en desarrollo local o ejecución de tests
        sin consumo de tokens externos ni dependencia de conexión de red.
        """
        logger.info("[AI_MOCK_MODE] Generando contenido simulado para prompt: %s", prompt[:60])
        time.sleep(0.3)

        mock_html = (
            f"<section class='ia-generated-content'>"
            f"<h3>Contenido Asistido por IA</h3>"
            f"<p>Este es un fragmento generado para la idea: <em>{prompt}</em>.</p>"
            f"<p>La persistencia híbrida entre PostgreSQL y MongoDB Atlas se validó correctamente.</p>"
            f"</section>"
        )

        return {
            "html": mock_html,
            "tokens_used": 120,
            "provider": "openrouter (mock)",
            "model": model,
        }

    def _call_openrouter(self, prompt: str, system_prompt: str, model: str) -> Dict[str, Any]:
        if not self.api_key:
            logger.error("OPENROUTER_API_KEY no encontrada en las variables de entorno.")
            raise AIServiceUnavailableError("Las credenciales del proveedor de IA no están configuradas.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://pintaebook.com",
            "X-Title": "Pinta Ebook Backend",
            "Content-Type": "application/json",
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        else:
            default_system = (
                "Eres un redactor y editor profesional de e-books. "
                "Responde únicamente con código HTML semántico (<p>, <h3>, <ul>, <li>, <strong>), "
                "sin bloques markdown (```html), sin la etiqueta <html> ni <body>."
            )
            messages.append({"role": "system", "content": default_system})

        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
        }

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                data=json.dumps(payload),
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            logger.error("Timeout al contactar con OpenRouter tras %s segundos", self.timeout)
            raise AITimeoutError() from exc
        except requests.RequestException as exc:
            logger.exception("Error de red conectando con OpenRouter: %s", exc)
            raise AIServiceUnavailableError() from exc

        if response.status_code != 200:
            logger.error("OpenRouter respondió código de error %s: %s", response.status_code, response.text)
            raise AIServiceUnavailableError("El motor de IA devolvió un error inesperado al procesar la solicitud.")

        data = response.json()
        try:
            content_html = data['choices'][0]['message']['content']
            tokens_used = data.get('usage', {}).get('total_tokens', 0)
        except (KeyError, IndexError) as exc:
            logger.error("Estructura de respuesta inesperada desde OpenRouter: %s", data)
            raise AIServiceUnavailableError("Respuesta de IA malformada.") from exc

        return {
            "html": content_html,
            "tokens_used": tokens_used,
            "provider": "openrouter",
            "model": model,
        }
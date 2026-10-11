import logging
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

import requests
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)


class PaymentGatewayError(APIException):
    """La pasarela respondió con un error o con datos inválidos (HTTP 502)."""
    status_code = 502
    default_detail = 'La pasarela de pagos devolvió una respuesta inesperada. Intente nuevamente más tarde.'
    default_code = 'payment_gateway_error'


class PaymentGatewayUnavailableError(PaymentGatewayError):
    """La pasarela no responde, tardó demasiado o está caída (HTTP 503)."""
    status_code = 503
    default_detail = 'La pasarela de pagos no está disponible en este momento. Intente nuevamente más tarde.'
    default_code = 'payment_gateway_unavailable'


class PaymentNotFoundError(PaymentGatewayError):
    """Mercado Pago no conoce ese Payment ID (HTTP 404)."""
    status_code = 404
    default_detail = 'El pago no existe en la pasarela.'
    default_code = 'payment_not_found'


def _env_flag(name: str, default: str = 'False') -> bool:
    return os.getenv(name, default).lower() in ('true', '1', 't')


class MercadoPagoClient:
    """
    Cliente de infraestructura para la API de Mercado Pago (Checkout Pro).
    Aísla el servicio de los detalles de red y del formato de la pasarela:
    el resto del código solo conoce create_preference(), get_payment() y las
    excepciones PaymentGatewayError / PaymentGatewayUnavailableError /
    PaymentNotFoundError.
    """

    PREFERENCES_PATH = '/checkout/preferences'
    PAYMENTS_PATH = '/v1/payments'
    CURRENCY_ID = 'ARS'  # Por ahora todos los paquetes se cobran en pesos argentinos.

    def __init__(self):
        self.access_token = os.getenv('MERCADOPAGO_ACCESS_TOKEN', '')
        self.base_url = os.getenv('MERCADOPAGO_BASE_URL', 'https://api.mercadopago.com').rstrip('/')
        self.sandbox = _env_flag('MERCADOPAGO_SANDBOX')
        self.mock_mode = _env_flag('MERCADOPAGO_MOCK_MODE')
        self.back_url_success = os.getenv('MERCADOPAGO_BACK_URL_SUCCESS', '')
        self.back_url_failure = os.getenv('MERCADOPAGO_BACK_URL_FAILURE', '')
        self.back_url_pending = os.getenv('MERCADOPAGO_BACK_URL_PENDING', '')
        self.timeout = 10  # Timeout en segundos

    def create_preference(
        self,
        title: str,
        unit_price: Decimal,
        external_reference: str,
    ) -> Dict[str, str]:
        """
        Crea una preferencia de pago y retorna un diccionario normalizado:
        {
            "preference_id": "123456-abc...",
            "init_point": "https://..."   # sandbox_init_point si MERCADOPAGO_SANDBOX está activo
        }
        """
        if self.mock_mode:
            return self._mock_preference(external_reference)

        return self._call_mercadopago(title, unit_price, external_reference)

    def get_payment(self, payment_id: str) -> Dict[str, Any]:
        """
        Consulta un pago en Mercado Pago y retorna sus datos normalizados:
        {
            "status": "approved",
            "external_reference": "42",
            "transaction_amount": Decimal("1500.00"),
            "currency_id": "ARS",
        }
        No tiene modo mock: los tests parchean este método.
        """
        if not self.access_token:
            logger.error("MERCADOPAGO_ACCESS_TOKEN no encontrada en las variables de entorno.")
            raise PaymentGatewayUnavailableError()

        headers = {'Authorization': f'Bearer {self.access_token}'}

        try:
            response = requests.get(
                f'{self.base_url}{self.PAYMENTS_PATH}/{payment_id}',
                headers=headers,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            logger.error("Timeout consultando el pago %s tras %s segundos", payment_id, self.timeout)
            raise PaymentGatewayUnavailableError() from exc
        except requests.RequestException as exc:
            logger.exception("Error de red consultando el pago %s: %s", payment_id, exc)
            raise PaymentGatewayUnavailableError() from exc

        if response.status_code == 404:
            logger.warning("Mercado Pago no conoce el pago %s", payment_id)
            raise PaymentNotFoundError()

        if response.status_code >= 500 or response.status_code == 429:
            logger.error("Mercado Pago no disponible (código %s): %s", response.status_code, response.text[:500])
            raise PaymentGatewayUnavailableError()

        if response.status_code != 200:
            logger.error("Mercado Pago rechazó la consulta del pago (código %s): %s", response.status_code, response.text[:500])
            raise PaymentGatewayError()

        try:
            data = response.json()
            return {
                'status': str(data['status']),
                'external_reference': str(data.get('external_reference') or ''),
                # str() antes de Decimal: Decimal(1500.1) arrastra errores de float.
                'transaction_amount': Decimal(str(data['transaction_amount'])),
                'currency_id': data.get('currency_id'),
            }
        except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
            logger.error("Respuesta de pago malformada desde Mercado Pago: %s", response.text[:500])
            raise PaymentGatewayError() from exc

    def _mock_preference(self, external_reference: str) -> Dict[str, str]:
        """
        Respuesta simulada para desarrollo local y tests, sin credenciales ni red.
        """
        preference_id = f'MOCK-{uuid.uuid4().hex}'
        logger.info(
            "[MERCADOPAGO_MOCK_MODE] Preferencia simulada %s (external_reference=%s)",
            preference_id,
            external_reference,
        )
        return {
            'preference_id': preference_id,
            'init_point': f'https://example.com/mock-checkout?pref_id={preference_id}',
        }

    def _call_mercadopago(self, title: str, unit_price: Decimal, external_reference: str) -> Dict[str, str]:
        if not self.access_token:
            logger.error("MERCADOPAGO_ACCESS_TOKEN no encontrada en las variables de entorno.")
            raise PaymentGatewayUnavailableError()

        payload = {
            'items': [
                {
                    'title': title,
                    'quantity': 1,
                    # El JSON no serializa Decimal; se convierte solo en este borde.
                    'unit_price': float(unit_price),
                    'currency_id': self.CURRENCY_ID,
                }
            ],
            'external_reference': external_reference,
        }

        # auto_return solo funciona si hay back_urls válidas, por eso van juntas.
        if self.back_url_success:
            payload['back_urls'] = {
                'success': self.back_url_success,
                'failure': self.back_url_failure or self.back_url_success,
                'pending': self.back_url_pending or self.back_url_success,
            }
            payload['auto_return'] = 'approved'

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

        try:
            response = requests.post(
                f'{self.base_url}{self.PREFERENCES_PATH}',
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            logger.error("Timeout al contactar con Mercado Pago tras %s segundos", self.timeout)
            raise PaymentGatewayUnavailableError() from exc
        except requests.RequestException as exc:
            logger.exception("Error de red conectando con Mercado Pago: %s", exc)
            raise PaymentGatewayUnavailableError() from exc

        # 5xx y 429: la pasarela está caída o saturada -> 503
        if response.status_code >= 500 or response.status_code == 429:
            logger.error("Mercado Pago no disponible (código %s): %s", response.status_code, response.text[:500])
            raise PaymentGatewayUnavailableError()

        # Otro código que no sea éxito (credenciales inválidas, pedido rechazado) -> 502
        if response.status_code not in (200, 201):
            logger.error("Mercado Pago rechazó la preferencia (código %s): %s", response.status_code, response.text[:500])
            raise PaymentGatewayError()

        try:
            data = response.json()
            preference_id = data['id']
            init_point = data['sandbox_init_point'] if self.sandbox else data['init_point']
        except (ValueError, KeyError, TypeError) as exc:
            logger.error("Respuesta de preferencia malformada desde Mercado Pago: %s", response.text[:500])
            raise PaymentGatewayError() from exc

        if not preference_id or not init_point:
            logger.error("Mercado Pago devolvió una preferencia sin id o sin init_point: %s", response.text[:500])
            raise PaymentGatewayError()

        return {
            'preference_id': str(preference_id),
            'init_point': init_point,
        }
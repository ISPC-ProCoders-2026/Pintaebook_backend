import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from infrastructure.mercadopago_client import (
    MercadoPagoClient,
    PaymentGatewayError,
    PaymentGatewayUnavailableError,
    PaymentNotFoundError,
)
from .models import CreditPackage, EstadoTransaccion, PaymentTransaction

User = get_user_model()


class CheckoutTests(APITestCase):
    """POST /api/billing/checkout/ con el cliente de Mercado Pago reemplazado por uno falso."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='comprador@test.com',
            password='Clave-Segura-123',
            first_name='Carlos',
            last_name='Comprador',
        )
        self.paquete = CreditPackage.objects.create(
            nombre='Pack 100',
            cantidad_creditos=100,
            precio=Decimal('9.99'),
        )
        self.url = '/api/billing/checkout/'
        self.client.force_authenticate(user=self.user)

        # Los tests nunca tocan la red: el cliente real se reemplaza por un doble.
        patcher = patch('apps.billing.services.MercadoPagoClient')
        self.addCleanup(patcher.stop)
        self.gateway = patcher.start().return_value
        self.gateway.create_preference.return_value = {
            'preference_id': 'PREF-123',
            'init_point': 'https://pago.test/init',
        }

    def _post(self, body=None):
        if body is None:
            body = {'paquete_id': self.paquete.pk}
        return self.client.post(self.url, body, format='json')

    def test_checkout_exitoso_retorna_201_con_init_point(self):
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data, {'init_point': 'https://pago.test/init'})

    def test_checkout_registra_transaccion_pendiente(self):
        self._post()

        transaccion = PaymentTransaction.objects.get()
        self.assertEqual(transaccion.usuario, self.user)
        self.assertEqual(transaccion.paquete, self.paquete)
        self.assertEqual(transaccion.id_transaccion_externa, 'PREF-123')
        self.assertEqual(transaccion.monto, Decimal('9.99'))
        self.assertEqual(transaccion.estado_transaccion, EstadoTransaccion.PENDIENTE)

    def test_checkout_envia_a_la_pasarela_titulo_precio_y_referencia(self):
        self._post()

        # La referencia es el ID de la transacción: así el webhook sabe
        # exactamente qué fila acreditar cuando Mercado Pago avisa del pago.
        transaccion = PaymentTransaction.objects.get()
        self.gateway.create_preference.assert_called_once_with(
            title='Pack 100',
            unit_price=Decimal('9.99'),
            external_reference=str(transaccion.pk),
        )

    def test_checkout_ignora_el_monto_enviado_en_el_body(self):
        response = self._post({'paquete_id': self.paquete.pk, 'monto': 1})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(PaymentTransaction.objects.get().monto, Decimal('9.99'))
        self.assertEqual(
            self.gateway.create_preference.call_args.kwargs['unit_price'],
            Decimal('9.99'),
        )

    def test_checkout_paquete_inexistente_retorna_404(self):
        response = self._post({'paquete_id': 999999})

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.gateway.create_preference.assert_not_called()
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_checkout_paquete_gratuito_retorna_400_y_no_llama_a_la_pasarela(self):
        gratis = CreditPackage.objects.create(
            nombre='Pack gratis',
            cantidad_creditos=10,
            precio=Decimal('0'),
        )

        response = self._post({'paquete_id': gratis.pk})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.gateway.create_preference.assert_not_called()
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_checkout_body_invalido_retorna_400(self):
        bodies = [{}, {'paquete_id': 'abc'}, {'paquete_id': 0}, {'paquete_id': -5}, {'paquete_id': None}]
        for body in bodies:
            with self.subTest(body=body):
                response = self._post(body)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.gateway.create_preference.assert_not_called()
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_checkout_sin_autenticar_retorna_401(self):
        self.client.force_authenticate(user=None)

        response = self._post()

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.gateway.create_preference.assert_not_called()
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_checkout_pasarela_caida_retorna_503_y_deja_transaccion_fallida(self):
        self.gateway.create_preference.side_effect = PaymentGatewayUnavailableError()

        response = self._post()

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        # No queda ningún pendiente huérfano: la fila se cierra como 'fallido'.
        transaccion = PaymentTransaction.objects.get()
        self.assertEqual(transaccion.estado_transaccion, EstadoTransaccion.FALLIDO)

    def test_checkout_pasarela_rechaza_retorna_502_y_deja_transaccion_fallida(self):
        self.gateway.create_preference.side_effect = PaymentGatewayError()

        response = self._post()

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        transaccion = PaymentTransaction.objects.get()
        self.assertEqual(transaccion.estado_transaccion, EstadoTransaccion.FALLIDO)


class MercadoPagoClientTests(SimpleTestCase):
    """Cliente de infraestructura: requests.post se reemplaza, no hay red ni base de datos."""

    URL = 'https://api.mercadopago.com/checkout/preferences'
    PAYMENT_URL = 'https://api.mercadopago.com/v1/payments/123'

    def _client(self, **overrides):
        # Se fijan TODAS las variables para que el entorno del contenedor no influya.
        env = {
            'MERCADOPAGO_ACCESS_TOKEN': 'TEST-token',
            'MERCADOPAGO_BASE_URL': 'https://api.mercadopago.com',
            'MERCADOPAGO_SANDBOX': 'False',
            'MERCADOPAGO_MOCK_MODE': 'False',
            'MERCADOPAGO_BACK_URL_SUCCESS': '',
            'MERCADOPAGO_BACK_URL_FAILURE': '',
            'MERCADOPAGO_BACK_URL_PENDING': '',
        }
        env.update(overrides)
        with patch.dict(os.environ, env):
            return MercadoPagoClient()

    @staticmethod
    def _response(status_code=201, json_data=None, text=''):
        response = MagicMock()
        response.status_code = status_code
        response.text = text
        response.json.return_value = json_data
        return response

    @staticmethod
    def _create(client):
        return client.create_preference(
            title='Pack 100',
            unit_price=Decimal('9.99'),
            external_reference='usuario:1',
        )

    @staticmethod
    def _preferencia_ok():
        return {
            'id': 'PREF-1',
            'init_point': 'https://mp.test/prod',
            'sandbox_init_point': 'https://mp.test/sandbox',
        }

    @staticmethod
    def _pago_ok():
        return {
            'status': 'approved',
            'external_reference': '7',
            'transaction_amount': 1500.5,
            'currency_id': 'ARS',
        }

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_retorna_init_point_de_produccion(self, mock_post):
        mock_post.return_value = self._response(201, self._preferencia_ok())

        result = self._create(self._client())

        self.assertEqual(result, {'preference_id': 'PREF-1', 'init_point': 'https://mp.test/prod'})

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_retorna_sandbox_init_point_en_modo_sandbox(self, mock_post):
        mock_post.return_value = self._response(201, self._preferencia_ok())

        result = self._create(self._client(MERCADOPAGO_SANDBOX='True'))

        self.assertEqual(result['init_point'], 'https://mp.test/sandbox')

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_envia_url_headers_y_payload_esperados(self, mock_post):
        mock_post.return_value = self._response(201, self._preferencia_ok())
        client = self._client()

        self._create(client)

        self.assertEqual(mock_post.call_args.args[0], self.URL)
        kwargs = mock_post.call_args.kwargs
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer TEST-token')
        self.assertEqual(kwargs['timeout'], client.timeout)
        self.assertEqual(kwargs['json']['external_reference'], 'usuario:1')
        self.assertEqual(
            kwargs['json']['items'],
            [{'title': 'Pack 100', 'quantity': 1, 'unit_price': 9.99, 'currency_id': 'ARS'}],
        )

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_no_envia_back_urls_si_no_estan_configuradas(self, mock_post):
        mock_post.return_value = self._response(201, self._preferencia_ok())

        self._create(self._client())

        payload = mock_post.call_args.kwargs['json']
        self.assertNotIn('back_urls', payload)
        self.assertNotIn('auto_return', payload)

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_envia_back_urls_y_auto_return_si_estan_configuradas(self, mock_post):
        mock_post.return_value = self._response(201, self._preferencia_ok())

        self._create(self._client(MERCADOPAGO_BACK_URL_SUCCESS='https://front.test/ok'))

        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(payload['auto_return'], 'approved')
        self.assertEqual(
            payload['back_urls'],
            {
                'success': 'https://front.test/ok',
                'failure': 'https://front.test/ok',
                'pending': 'https://front.test/ok',
            },
        )

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_timeout_lanza_error_503(self, mock_post):
        mock_post.side_effect = requests.Timeout()

        with self.assertRaises(PaymentGatewayUnavailableError) as ctx:
            self._create(self._client())

        self.assertEqual(ctx.exception.status_code, 503)

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_error_de_conexion_lanza_error_503(self, mock_post):
        mock_post.side_effect = requests.ConnectionError()

        with self.assertRaises(PaymentGatewayUnavailableError) as ctx:
            self._create(self._client())

        self.assertEqual(ctx.exception.status_code, 503)

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_codigos_5xx_y_429_lanzan_error_503(self, mock_post):
        for code in (500, 502, 503, 429):
            with self.subTest(status_code=code):
                mock_post.return_value = self._response(code, text='error')
                with self.assertRaises(PaymentGatewayError) as ctx:
                    self._create(self._client())
                self.assertEqual(ctx.exception.status_code, 503)

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_rechazos_4xx_lanzan_error_502(self, mock_post):
        for code in (400, 401, 403, 404):
            with self.subTest(status_code=code):
                mock_post.return_value = self._response(code, text='rechazado')
                with self.assertRaises(PaymentGatewayError) as ctx:
                    self._create(self._client())
                self.assertEqual(ctx.exception.status_code, 502)

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_respuesta_sin_init_point_lanza_error_502(self, mock_post):
        mock_post.return_value = self._response(201, {'id': 'PREF-1'})

        with self.assertRaises(PaymentGatewayError) as ctx:
            self._create(self._client())

        self.assertEqual(ctx.exception.status_code, 502)

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_respuesta_que_no_es_json_lanza_error_502(self, mock_post):
        respuesta = self._response(201, text='<html>no es json</html>')
        respuesta.json.side_effect = ValueError('no es json')
        mock_post.return_value = respuesta

        with self.assertRaises(PaymentGatewayError) as ctx:
            self._create(self._client())

        self.assertEqual(ctx.exception.status_code, 502)

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_sin_access_token_lanza_error_503_sin_llamar_a_la_red(self, mock_post):
        with self.assertRaises(PaymentGatewayUnavailableError):
            self._create(self._client(MERCADOPAGO_ACCESS_TOKEN=''))

        mock_post.assert_not_called()

    @patch('infrastructure.mercadopago_client.requests.post')
    def test_mock_mode_no_llama_a_la_red(self, mock_post):
        result = self._create(self._client(MERCADOPAGO_MOCK_MODE='true', MERCADOPAGO_ACCESS_TOKEN=''))

        mock_post.assert_not_called()
        self.assertTrue(result['preference_id'].startswith('MOCK-'))
        self.assertIn(result['preference_id'], result['init_point'])

    # --- get_payment (consulta del pago para el webhook) ---

    @patch('infrastructure.mercadopago_client.requests.get')
    def test_get_payment_normaliza_la_respuesta(self, mock_get):
        mock_get.return_value = self._response(200, self._pago_ok())
        client = self._client()

        result = client.get_payment('123')

        self.assertEqual(
            result,
            {
                'status': 'approved',
                'external_reference': '7',
                'transaction_amount': Decimal('1500.5'),
                'currency_id': 'ARS',
            },
        )
        self.assertEqual(mock_get.call_args.args[0], self.PAYMENT_URL)
        self.assertEqual(mock_get.call_args.kwargs['headers']['Authorization'], 'Bearer TEST-token')
        self.assertEqual(mock_get.call_args.kwargs['timeout'], client.timeout)

    @patch('infrastructure.mercadopago_client.requests.get')
    def test_get_payment_inexistente_lanza_error_404(self, mock_get):
        mock_get.return_value = self._response(404, text='not found')

        with self.assertRaises(PaymentNotFoundError) as ctx:
            self._client().get_payment('123')

        self.assertEqual(ctx.exception.status_code, 404)

    @patch('infrastructure.mercadopago_client.requests.get')
    def test_get_payment_pasarela_caida_lanza_error_503(self, mock_get):
        for code in (500, 503, 429):
            with self.subTest(status_code=code):
                mock_get.return_value = self._response(code, text='error')
                with self.assertRaises(PaymentGatewayUnavailableError) as ctx:
                    self._client().get_payment('123')
                self.assertEqual(ctx.exception.status_code, 503)

    @patch('infrastructure.mercadopago_client.requests.get')
    def test_get_payment_sin_access_token_no_llama_a_la_red(self, mock_get):
        with self.assertRaises(PaymentGatewayUnavailableError):
            self._client(MERCADOPAGO_ACCESS_TOKEN='').get_payment('123')

        mock_get.assert_not_called()
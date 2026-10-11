from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.billing.models import CreditBalance, CreditPackage, EstadoTransaccion, PaymentTransaction
from apps.billing.services import BillingService

GET_PAYMENT = 'infrastructure.mercadopago_client.MercadoPagoClient.get_payment'


class WebhookTests(APITestCase):
    URL = '/api/billing/webhook/'

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email='comprador@example.com', password='Passw0rd!123',
            first_name='Test', last_name='User',
        )
        self.package = CreditPackage.objects.create(
            nombre='Pack 500', cantidad_creditos=500, precio=Decimal('1500.00'),
        )
        self.tx = PaymentTransaction.objects.create(
            usuario=self.user, paquete=self.package, id_transaccion_externa='pref-1',
            monto=Decimal('1500.00'), estado_transaccion=EstadoTransaccion.PENDIENTE,
        )
        self.initial_credits = CreditBalance.objects.get(usuario=self.user).credits_available

    def _payment(self, **overrides):
        payment = {
            'status': 'approved',
            'external_reference': str(self.tx.pk),
            'transaction_amount': Decimal('1500.00'),
            'currency_id': 'ARS',
        }
        payment.update(overrides)
        return payment

    def _post(self, payment_id='123'):
        return self.client.post(self.URL, {'type': 'payment', 'data': {'id': payment_id}}, format='json')

    def _credits(self):
        return CreditBalance.objects.get(usuario=self.user).credits_available

    def test_pago_aprobado_acredita_creditos_sin_jwt(self):
        with patch(GET_PAYMENT, return_value=self._payment()):
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado_transaccion, EstadoTransaccion.APROBADO)
        self.assertEqual(self._credits(), self.initial_credits + 500)

    def test_webhook_repetido_no_acredita_dos_veces(self):
        with patch(GET_PAYMENT, return_value=self._payment()):
            self._post()
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._credits(), self.initial_credits + 500)

    def test_monto_distinto_no_acredita(self):
        with patch(GET_PAYMENT, return_value=self._payment(transaction_amount=Decimal('1.00'))):
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado_transaccion, EstadoTransaccion.PENDIENTE)
        self.assertEqual(self._credits(), self.initial_credits)

    def test_pago_rechazado_marca_fallido_sin_acreditar(self):
        with patch(GET_PAYMENT, return_value=self._payment(status='rejected')):
            self._post()
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado_transaccion, EstadoTransaccion.FALLIDO)
        self.assertEqual(self._credits(), self.initial_credits)

    def test_rechazado_y_luego_aprobado_acredita(self):
        with patch(GET_PAYMENT, return_value=self._payment(status='rejected')):
            self._post('111')
        with patch(GET_PAYMENT, return_value=self._payment()):
            self._post('222')
        self.assertEqual(self._credits(), self.initial_credits + 500)

    def test_notificacion_que_no_es_payment_se_ignora(self):
        with patch(GET_PAYMENT) as mock_get:
            response = self.client.post(self.URL, {'type': 'merchant_order', 'data': {'id': '1'}}, format='json')
        self.assertEqual(response.status_code, 200)
        mock_get.assert_not_called()

    def test_payment_id_invalido_devuelve_400(self):
        response = self._post('../../x')
        self.assertEqual(response.status_code, 400)


class FakeGateway:
    """Cliente falso para probar el checkout sin red."""

    def __init__(self, error=None):
        self.error = error
        self.external_references = []

    def create_preference(self, title, unit_price, external_reference):
        self.external_references.append(external_reference)
        if self.error:
            raise self.error
        return {'preference_id': 'pref-xyz', 'init_point': 'https://example.com/pay'}


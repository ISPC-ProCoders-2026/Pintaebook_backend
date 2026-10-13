from decimal import Decimal
from unittest.mock import patch

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.billing.models import CreditPackage, EstadoTransaccion, PaymentTransaction
from apps.billing.models import CreditBalance
from apps.ebooks.models import EbookMetadata
from core.ws_auth import JWTAuthMiddlewareStack

from .routing import websocket_urlpatterns
from .services import group_name, notify_user

User = get_user_model()

IN_MEMORY_LAYER = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

application = JWTAuthMiddlewareStack(URLRouter(websocket_urlpatterns))


def _make_user(email):
    return User.objects.create_user(
        email=email, password='Clave-Segura-123', first_name='Test', last_name='User',
    )


def _communicator(user=None, path='/ws/notifications/'):
    if user is not None:
        path = f'{path}?token={AccessToken.for_user(user)}'
    return WebsocketCommunicator(application, path)


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class NotificationConsumerTests(TransactionTestCase):
    """WebSocket ws/notifications/ (necesita TransactionTestCase: usa hilos de BD)."""

    def setUp(self):
        self.user = _make_user('a@test.com')
        self.other = _make_user('b@test.com')

    async def test_rechaza_conexion_sin_token(self):
        communicator = _communicator()
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    async def test_rechaza_token_invalido(self):
        communicator = WebsocketCommunicator(application, '/ws/notifications/?token=basura')
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    async def test_usuario_autenticado_recibe_su_notificacion(self):
        communicator = _communicator(self.user)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        layer = get_channel_layer()
        await layer.group_send(
            group_name(self.user.id),
            {'type': 'notification.message', 'payload': {'type': 'notification', 'event': 'info'}},
        )

        message = await communicator.receive_json_from()
        self.assertEqual(message, {'type': 'notification', 'event': 'info'})
        await communicator.disconnect()

    async def test_no_recibe_notificaciones_de_otro_usuario(self):
        communicator = _communicator(self.user)
        await communicator.connect()

        layer = get_channel_layer()
        await layer.group_send(
            group_name(self.other.id),
            {'type': 'notification.message', 'payload': {'event': 'ajena'}},
        )

        self.assertTrue(await communicator.receive_nothing())
        await communicator.disconnect()

    async def test_varias_pestanas_reciben_la_misma_notificacion(self):
        tab1, tab2 = _communicator(self.user), _communicator(self.user)
        await tab1.connect()
        await tab2.connect()

        layer = get_channel_layer()
        await layer.group_send(
            group_name(self.user.id),
            {'type': 'notification.message', 'payload': {'event': 'x'}},
        )

        self.assertEqual((await tab1.receive_json_from())['event'], 'x')
        self.assertEqual((await tab2.receive_json_from())['event'], 'x')
        await tab1.disconnect()
        await tab2.disconnect()


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class NotifyUserServiceTests(TestCase):
    """notify_user: formato del mensaje y envío al confirmar la transacción."""

    def _receive(self, channel):
        return async_to_sync(get_channel_layer().receive)(channel)

    def _subscribe(self, user_id):
        layer = get_channel_layer()
        channel = async_to_sync(layer.new_channel)()
        async_to_sync(layer.group_add)(group_name(user_id), channel)
        return channel

    def test_envia_el_mensaje_con_el_formato_documentado(self):
        channel = self._subscribe('u1')

        with self.captureOnCommitCallbacks(execute=True):
            notify_user('u1', 'credits_purchased', 'Titulo', 'Mensaje',
                        level='success', data={'credits_added': 100})

        event = self._receive(channel)
        self.assertEqual(event['type'], 'notification.message')
        payload = event['payload']
        self.assertEqual(payload['type'], 'notification')
        self.assertEqual(payload['event'], 'credits_purchased')
        self.assertEqual(payload['level'], 'success')
        self.assertEqual(payload['title'], 'Titulo')
        self.assertEqual(payload['message'], 'Mensaje')
        self.assertEqual(payload['data'], {'credits_added': 100})
        self.assertIn('timestamp', payload)

    def test_level_invalido_se_normaliza_a_info(self):
        channel = self._subscribe('u1')

        with self.captureOnCommitCallbacks(execute=True):
            notify_user('u1', 'x', 'T', 'M', level='inventado')

        self.assertEqual(self._receive(channel)['payload']['level'], 'info')

    def test_no_envia_si_la_transaccion_se_revierte(self):
        channel = self._subscribe('u1')

        class Rollback(Exception):
            pass

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    notify_user('u1', 'x', 'T', 'M')
                    raise Rollback()
            except Rollback:
                pass

        self.assertEqual(callbacks, [])

    def test_un_fallo_del_channel_layer_no_rompe_el_flujo(self):
        with patch('apps.notifications.services.get_channel_layer', side_effect=RuntimeError('redis caido')):
            with self.captureOnCommitCallbacks(execute=True):
                notify_user('u1', 'x', 'T', 'M')  # no debe levantar


class BillingNotificationTests(APITestCase):
    """El webhook de Mercado Pago dispara las notificaciones del usuario."""

    URL = '/api/billing/webhook/'
    GET_PAYMENT = 'infrastructure.mercadopago_client.MercadoPagoClient.get_payment'

    def setUp(self):
        self.user = _make_user('comprador@test.com')
        self.package = CreditPackage.objects.create(
            nombre='Pack 500', cantidad_creditos=500, precio=Decimal('1500.00'),
        )
        self.tx = PaymentTransaction.objects.create(
            usuario=self.user, paquete=self.package, id_transaccion_externa='pref-n1',
            monto=Decimal('1500.00'), estado_transaccion=EstadoTransaccion.PENDIENTE,
        )

    def _payment(self, status='approved'):
        return {
            'status': status,
            'external_reference': str(self.tx.pk),
            'transaction_amount': Decimal('1500.00'),
            'currency_id': 'ARS',
        }

    def _post(self):
        return self.client.post(self.URL, {'type': 'payment', 'data': {'id': '1'}}, format='json')

    @patch('apps.billing.services.notify_user')
    def test_pago_aprobado_notifica_creditos_acreditados(self, mock_notify):
        with patch(self.GET_PAYMENT, return_value=self._payment()):
            self._post()

        mock_notify.assert_called_once()
        args, kwargs = mock_notify.call_args
        self.assertEqual(args[0], self.user.id)
        self.assertEqual(args[1], 'credits_purchased')
        self.assertEqual(kwargs['level'], 'success')
        saldo = CreditBalance.objects.get(usuario=self.user).credits_available
        self.assertEqual(kwargs['data']['credits_added'], 500)
        self.assertEqual(kwargs['data']['credits_available'], saldo)

    @patch('apps.billing.services.notify_user')
    def test_webhook_repetido_no_notifica_dos_veces(self, mock_notify):
        with patch(self.GET_PAYMENT, return_value=self._payment()):
            self._post()
            self._post()

        self.assertEqual(mock_notify.call_count, 1)

    @patch('apps.billing.services.notify_user')
    def test_pago_rechazado_notifica_pago_fallido(self, mock_notify):
        with patch(self.GET_PAYMENT, return_value=self._payment('rejected')):
            self._post()

        mock_notify.assert_called_once()
        args, kwargs = mock_notify.call_args
        self.assertEqual(args[1], 'payment_failed')
        self.assertEqual(kwargs['level'], 'error')

    @patch('apps.billing.services.notify_user')
    def test_pago_pendiente_no_notifica(self, mock_notify):
        with patch(self.GET_PAYMENT, return_value=self._payment('in_process')):
            self._post()

        mock_notify.assert_not_called()


class ExportNotificationTests(APITestCase):
    """La exportación a EPUB notifica al autor."""

    def setUp(self):
        self.user = _make_user('autor@test.com')
        self.ebook = EbookMetadata.objects.create(
            author=self.user, title='Mi Libro', description='d', status='COMPLETED',
        )
        self.client.force_authenticate(user=self.user)
        self.content = {
            'ebook_id': str(self.ebook.id),
            'chapters': [{'id': 'c1', 'title': 'Cap 1', 'sections': [
                {'id': 's1', 'title': 'Sec', 'html': '<p>Hola</p>'},
            ]}],
        }

    @patch('apps.exporter.views.notify_user')
    @patch('apps.exporter.views.content_services.get_content')
    def test_exportar_epub_notifica_epub_listo(self, mock_content, mock_notify):
        mock_content.return_value = self.content

        response = self.client.get(f'/api/ebooks/{self.ebook.id}/export/epub/')

        self.assertEqual(response.status_code, 200)
        mock_notify.assert_called_once()
        args, kwargs = mock_notify.call_args
        self.assertEqual(args[0], self.user.id)
        self.assertEqual(args[1], 'epub_ready')
        self.assertEqual(kwargs['data']['ebook_id'], str(self.ebook.id))
        self.assertEqual(kwargs['data']['filename'], 'mi-libro.epub')

    @patch('apps.exporter.views.notify_user')
    def test_ebook_no_completado_no_notifica(self, mock_notify):
        self.ebook.status = 'PROCESSING'
        self.ebook.save()

        response = self.client.get(f'/api/ebooks/{self.ebook.id}/export/epub/')

        self.assertEqual(response.status_code, 409)
        mock_notify.assert_not_called()

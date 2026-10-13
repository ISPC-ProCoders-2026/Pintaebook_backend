from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import CreditPackage, EstadoTransaccion, PaymentTransaction

User = get_user_model()


class BillingTransactionListTests(APITestCase):
    """GET /api/billing/transactions/ (historial de compras del usuario)."""

    URL = '/api/billing/transactions/'

    def setUp(self):
        self.user = User.objects.create_user(
            email='comprador@test.com',
            password='Clave-Segura-123',
            first_name='Carla',
            last_name='Compradora',
        )
        self.other = User.objects.create_user(
            email='otro@test.com',
            password='Clave-Segura-123',
            first_name='Otto',
            last_name='Otro',
        )
        self.basico = CreditPackage.objects.get(nombre='Básico')
        self.pro = CreditPackage.objects.get(nombre='Pro')
        self._seq = 0

    def _tx(self, usuario, paquete, estado, monto='1000.00'):
        self._seq += 1
        return PaymentTransaction.objects.create(
            usuario=usuario,
            paquete=paquete,
            id_transaccion_externa=f'pref-{self._seq}',
            monto=Decimal(monto),
            estado_transaccion=estado,
        )

    def test_requiere_autenticacion(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_sin_compras_devuelve_lista_vacia_paginada(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])

    def test_devuelve_solo_las_compras_del_usuario(self):
        propia = self._tx(self.user, self.basico, EstadoTransaccion.APROBADO)
        self._tx(self.other, self.pro, EstadoTransaccion.APROBADO, '7000.00')
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.URL)

        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], propia.id)

    def test_orden_mas_reciente_primero(self):
        primera = self._tx(self.user, self.basico, EstadoTransaccion.APROBADO)
        segunda = self._tx(self.user, self.pro, EstadoTransaccion.PENDIENTE, '7000.00')
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.URL)

        ids = [t['id'] for t in response.data['results']]
        # La fecha la completa PostgreSQL con now(): en un mismo test pueden
        # coincidir, por eso el desempate es por id descendente.
        self.assertEqual(ids, [segunda.id, primera.id])

    def test_formato_de_cada_item(self):
        self._tx(self.user, self.pro, EstadoTransaccion.APROBADO, '7000.00')
        self.client.force_authenticate(user=self.user)

        item = self.client.get(self.URL).data['results'][0]

        self.assertEqual(set(item.keys()), {'id', 'paquete', 'monto', 'estado', 'fecha'})
        self.assertEqual(
            item['paquete'],
            {'id': self.pro.id, 'nombre': 'Pro', 'cantidad_creditos': 1000},
        )
        self.assertEqual(item['monto'], '7000.00')
        self.assertEqual(item['estado'], 'aprobado')

    def test_filtra_por_estado(self):
        aprobada = self._tx(self.user, self.basico, EstadoTransaccion.APROBADO)
        self._tx(self.user, self.basico, EstadoTransaccion.FALLIDO)
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.URL, {'estado': 'aprobado'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([t['id'] for t in response.data['results']], [aprobada.id])

    def test_estado_invalido_devuelve_400(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.URL, {'estado': 'inventado'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('estado', response.data)

    def test_pagina_de_diez_con_metadatos(self):
        for _ in range(12):
            self._tx(self.user, self.basico, EstadoTransaccion.APROBADO)
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.URL)

        self.assertEqual(response.data['count'], 12)
        self.assertEqual(len(response.data['results']), 10)
        self.assertIsNotNone(response.data['next'])

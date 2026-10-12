from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import CreditPackage

User = get_user_model()


class CreditPackageListTests(APITestCase):
    """GET /api/billing/packages/ y datos iniciales cargados por la migración 0003."""

    URL = '/api/billing/packages/'

    def setUp(self):
        self.user = User.objects.create_user(
            email='lector@test.com',
            password='Clave-Segura-123',
            first_name='Lucia',
            last_name='Lectora',
        )

    def test_la_migracion_carga_los_tres_paquetes_iniciales(self):
        nombres = set(CreditPackage.objects.values_list('nombre', flat=True))
        self.assertTrue({'Básico', 'Estándar', 'Pro'} <= nombres)

    def test_listado_requiere_autenticacion(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_listado_devuelve_paquetes_ordenados_por_precio(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        precios = [Decimal(p['precio']) for p in response.data]
        self.assertEqual(precios, sorted(precios))
        self.assertEqual(
            set(response.data[0].keys()),
            {'id', 'nombre', 'cantidad_creditos', 'precio'},
        )

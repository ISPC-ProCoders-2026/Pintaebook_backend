from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import CreditBalance
from .services import BillingService, InsufficientCreditsError

User = get_user_model()


class BillingTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='autor@test.com',
            password='Clave-Segura-123',
            first_name='Ana',
            last_name='Autora',
        )
        self.url = '/api/billing/balance/'
        self.client.force_authenticate(user=self.user)

    def test_signal_crea_balance_de_bienvenida(self):
      balance = CreditBalance.objects.get(usuario=self.user)
      self.assertEqual(balance.credits_available, 1000)

    def test_consultar_balance_autenticado_retorna_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['credits_available'], 100)
        self.assertIn('last_updated', response.data)

    def test_consultar_balance_autenticado_retorna_200(self):
     response = self.client.get(self.url)
     self.assertEqual(response.status_code, status.HTTP_200_OK)
     self.assertEqual(response.data['credits_available'], 1000)
     self.assertIn('last_updated', response.data)

    def test_deduct_credits_descuenta_correctamente(self):
     nuevo_saldo = BillingService.deduct_credits(self.user, 30)
     self.assertEqual(nuevo_saldo, 970)

     balance = CreditBalance.objects.get(usuario=self.user)
     self.assertEqual(balance.credits_available, 970)


   
    def test_deduct_credits_insuficientes_lanza_excepcion_402(self):
     with self.assertRaises(InsufficientCreditsError):
        BillingService.deduct_credits(self.user, 1500)

     balance = CreditBalance.objects.get(usuario=self.user)
     self.assertEqual(balance.credits_available, 1000)

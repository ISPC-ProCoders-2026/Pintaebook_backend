from unittest.mock import patch

from django.core import mail
from rest_framework import status
from rest_framework.test import APITestCase

REGISTER_URL = '/api/auth/register/'

PAYLOAD = {
    'email': 'nuevo@test.com',
    'password': 'Clave-Segura-123',
    'first_name': 'Ana',
    'last_name': 'Autora',
}


class WelcomeEmailTests(APITestCase):
    def test_registro_envia_correo_de_bienvenida(self):
        response = self.client.post(REGISTER_URL, PAYLOAD, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['nuevo@test.com'])
        self.assertIn('Bienvenido', mail.outbox[0].subject)
        self.assertIn('Ana', mail.outbox[0].body)

    def test_registro_invalido_no_envia_correo(self):
        response = self.client.post(
            REGISTER_URL, {**PAYLOAD, 'password': '123'}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)

    def test_fallo_de_envio_no_impide_el_registro(self):
        with patch('apps.accounts.services.send_mail', side_effect=Exception('Brevo caído')):
            response = self.client.post(REGISTER_URL, PAYLOAD, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.json())

import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PasswordResetOTP
from .services import OTP_MAX_ATTEMPTS, OTP_RESEND_COOLDOWN_SECONDS

User = get_user_model()

REQUEST_URL = '/api/auth/password-reset/request/'
CONFIRM_URL = '/api/auth/password-reset/confirm/'
OLD_PASSWORD = 'Clave-Segura-123'
NEW_PASSWORD = 'Otra-Clave-Nueva-456'


class PasswordResetOTPTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='autor@test.com',
            password=OLD_PASSWORD,
            first_name='Ana',
            last_name='Autora',
        )

    def _request_code(self, email='autor@test.com'):
        """Pide el OTP y lo lee del correo enviado."""
        mail.outbox.clear()
        response = self.client.post(REQUEST_URL, {'email': email}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        return re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)

    def _confirm(self, code, password=NEW_PASSWORD, email='autor@test.com'):
        return self.client.post(
            CONFIRM_URL,
            {'email': email, 'code': code, 'new_password': password},
            format='json',
        )

    def _expire_cooldown(self):
        PasswordResetOTP.objects.update(
            created_at=timezone.now() - timedelta(seconds=OTP_RESEND_COOLDOWN_SECONDS + 1)
        )

    # --- Paso 1: pedir el código ---

    def test_request_envia_correo_con_codigo_de_6_digitos(self):
        code = self._request_code()

        self.assertEqual(len(code), 6)
        self.assertEqual(mail.outbox[0].to, ['autor@test.com'])

    def test_request_guarda_hash_y_no_el_codigo(self):
        code = self._request_code()

        otp = PasswordResetOTP.objects.get(user=self.user)
        self.assertNotIn(code, otp.code_hash)
        self.assertEqual(len(otp.code_hash), 64)

    def test_request_con_correo_inexistente_responde_igual_y_no_envia(self):
        response = self.client.post(REQUEST_URL, {'email': 'nadie@test.com'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(PasswordResetOTP.objects.count(), 0)

    def test_request_no_requiere_token_ni_falla_con_token_invalido(self):
        response = self.client.post(
            REQUEST_URL, {'email': 'autor@test.com'}, format='json',
            HTTP_AUTHORIZATION='Bearer token-vencido',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_request_con_email_mal_formado_da_400(self):
        response = self.client.post(REQUEST_URL, {'email': 'no-es-email'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_request_repetido_dentro_del_cooldown_no_reenvia(self):
        self._request_code()
        mail.outbox.clear()

        response = self.client.post(REQUEST_URL, {'email': 'autor@test.com'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(PasswordResetOTP.objects.count(), 1)

    def test_nuevo_codigo_invalida_el_anterior(self):
        viejo = self._request_code()
        self._expire_cooldown()
        nuevo = self._request_code()

        self.assertNotEqual(viejo, nuevo)
        response = self._confirm(viejo)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._confirm(nuevo).status_code, status.HTTP_200_OK)

    def test_request_no_envia_a_usuario_inactivo(self):
        self.user.is_active = False
        self.user.save()

        self.client.post(REQUEST_URL, {'email': 'autor@test.com'}, format='json')

        self.assertEqual(len(mail.outbox), 0)

    # --- Paso 2: confirmar ---

    def test_flujo_completo_cambia_la_contrasena(self):
        code = self._request_code()

        response = self._confirm(code)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertFalse(self.user.check_password(OLD_PASSWORD))
        login = self.client.post(
            '/api/auth/login/',
            {'email': 'autor@test.com', 'password': NEW_PASSWORD},
            format='json',
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)

    def test_el_codigo_solo_sirve_una_vez(self):
        code = self._request_code()
        self.assertEqual(self._confirm(code).status_code, status.HTTP_200_OK)

        response = self._confirm(code, password='Tercera-Clave-789')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))

    def test_codigo_incorrecto_da_400_y_no_cambia_la_contrasena(self):
        code = self._request_code()
        wrong = '000000' if code != '000000' else '111111'

        response = self._confirm(wrong)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('code', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_codigo_vencido_es_rechazado(self):
        code = self._request_code()
        PasswordResetOTP.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        response = self._confirm(code)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_se_bloquea_tras_demasiados_intentos_aun_con_el_codigo_correcto(self):
        code = self._request_code()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(OTP_MAX_ATTEMPTS):
            self.assertEqual(self._confirm(wrong).status_code, status.HTTP_400_BAD_REQUEST)

        response = self._confirm(code)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_contrasena_debil_no_consume_el_codigo(self):
        code = self._request_code()

        response = self._confirm(code, password='12345678')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password', response.data)
        # El mismo código sigue siendo válido con una contraseña correcta.
        self.assertEqual(self._confirm(code).status_code, status.HTTP_200_OK)

    def test_correo_inexistente_responde_error_generico_de_codigo(self):
        response = self._confirm('123456', email='nadie@test.com')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('code', response.data)

    def test_codigo_con_formato_invalido_da_400(self):
        response = self._confirm('12ab56')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('code', response.data)

    def test_el_correo_no_distingue_mayusculas(self):
        code = self._request_code(email='AUTOR@Test.com')
        response = self._confirm(code, email='Autor@TEST.com')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

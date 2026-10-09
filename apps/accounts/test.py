from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Role
from .serializers import RegisterSerializer, UserSerializer

User = get_user_model()


class AccountsModelTests(APITestCase):
    def setUp(self):
        self.role, _ = Role.objects.get_or_create(
            nombre_rol=Role.RoleName.AUTOR
        )

    def test_usuario_se_crea_con_uuid_y_email(self):
        email = "autor@test.com"

        user = User.objects.create_user(
            email=email,
            password="Clave-Segura-123",
            first_name="Ana",
            last_name="Autora",
            role=self.role,
        )

        self.assertIsNotNone(user.id)
        self.assertEqual(user.email, email)
        self.assertTrue(user.check_password("Clave-Segura-123"))
        self.assertEqual(user.role, self.role)

    def test_str_de_role_devuelve_nombre_legible(self):
        role = self.role

        resultado = str(role)

        self.assertEqual(resultado, "Autor")


class AccountsSerializerTests(APITestCase):
    def setUp(self):
        self.role, _ = Role.objects.get_or_create(
            nombre_rol=Role.RoleName.AUTOR
        )
        self.user = User.objects.create_user(
            email="autor@test.com",
            password="Clave-Segura-123",
            first_name="Ana",
            last_name="Autora",
            role=self.role,
        )

    def test_register_serializer_normaliza_email(self):
        payload = {
            "email": "  NUEVO@test.com  ",
            "password": "Clave-Segura-123",
            "first_name": "Ana",
            "last_name": "Autora",
        }

        serializer = RegisterSerializer(data=payload)
        es_valido = serializer.is_valid()

        self.assertTrue(es_valido, serializer.errors)
        self.assertEqual(
            serializer.validated_data["email"],
            "nuevo@test.com",
        )

    def test_register_serializer_rechaza_email_duplicado(self):
        payload = {
            "email": "autor@test.com",
            "password": "Clave-Segura-123",
            "first_name": "Otra",
            "last_name": "Persona",
        }

        serializer = RegisterSerializer(data=payload)
        es_valido = serializer.is_valid()

        self.assertFalse(es_valido)
        self.assertIn("email", serializer.errors)

    def test_register_serializer_rechaza_password_corto(self):
        payload = {
            "email": "nuevo@test.com",
            "password": "abc",
            "first_name": "Nuevo",
            "last_name": "Usuario",
        }

        serializer = RegisterSerializer(data=payload)
        es_valido = serializer.is_valid()

        self.assertFalse(es_valido)
        self.assertIn("password", serializer.errors)

    def test_user_serializer_expone_rol_sin_exponer_password(self):
        user = self.user

        data = UserSerializer(user).data

        self.assertEqual(data["email"], "autor@test.com")
        self.assertEqual(data["role"], "AUTOR")
        self.assertNotIn("password", data)


class AccountsApiTests(APITestCase):
    def setUp(self):
        self.role, _ = Role.objects.get_or_create(
            nombre_rol=Role.RoleName.AUTOR
        )
        self.user = User.objects.create_user(
            email="autor@test.com",
            password="Clave-Segura-123",
            first_name="Ana",
            last_name="Autora",
            role=self.role,
        )

        self.register_url = "/api/auth/register/"
        self.login_url = "/api/auth/login/"
        self.me_url = "/api/auth/me/"
        self.google_url = "/api/auth/google/"

    def test_registro_valido_devuelve_201(self):
        payload = {
            "email": "nuevo@test.com",
            "password": "Otra-Clave-Segura-123",
            "first_name": "Nuevo",
            "last_name": "Usuario",
        }

        from unittest.mock import patch

        with patch(
            "apps.accounts.views.generate_tokens",
            return_value={
                "access": "access-test",
                "refresh": "refresh-test",
            },
        ):
            response = self.client.post(
                self.register_url, payload, format="json"
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertTrue(
            User.objects.filter(email="nuevo@test.com").exists()
        )
        self.assertEqual(response.data["access"], "access-test")

    def test_registro_con_payload_invalido_devuelve_400(self):
        payload = {
            "email": "email-invalido",
            "password": "abc",
            "first_name": "Nuevo",
            "last_name": "Usuario",
        }

        response = self.client.post(
            self.register_url, payload, format="json"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_login_con_credenciales_incorrectas_devuelve_401(self):
        payload = {
            "email": "autor@test.com",
            "password": "Contraseña-Incorrecta-123",
        }

        response = self.client.post(
            self.login_url, payload, format="json"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_me_sin_autenticacion_devuelve_401(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.me_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_me_autenticado_devuelve_datos_del_usuario(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.me_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(response.data["email"], self.user.email)
        self.assertNotIn("password", response.data)

    def test_register_no_permite_get_devuelve_405(self):
        response = self.client.get(self.register_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_me_no_permite_post_devuelve_405(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            self.me_url, {}, format="json"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_google_login_sin_id_token_devuelve_400(self):
        payload = {}

        response = self.client.post(
            self.google_url, payload, format="json"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
# pyrefly: ignore [missing-import]
from rest_framework_simplejwt.serializers import TokenRefreshSerializer

from .serializers import (
    GoogleAuthSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .services import (
    authenticate_google_user,
    confirm_password_reset,
    generate_tokens,
    request_password_reset,
)


# OAuth 2.0:
class GoogleLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = authenticate_google_user(serializer.validated_data['id_token'])
        user = result['user']
        tokens = result['tokens']

        return Response({
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'user': {
                'id': str(user.id),
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role.code if user.role else None,
            }
        }, status=status.HTTP_200_OK)

# AUTH JWT:
class RegisterView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        tokens = generate_tokens(user)

        return Response(
            {
                **tokens,
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            request=request,
            username=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )

        if user is None:
            return Response(
                {"detail": "Credenciales inválidas."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_active:
            return Response(
                {"detail": "La cuenta está inactiva."},
                status=status.HTTP_403_FORBIDDEN,
            )

        tokens = generate_tokens(user)

        return Response(
            {
                **tokens,
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetRequestView(APIView):
    """
    Paso 1 de la recuperación de contraseña: envía un OTP de 6 dígitos al correo.

    Responde siempre 200 con el mismo mensaje, exista o no la cuenta, para no
    revelar qué correos están registrados.
    """
    # Sin JWT: un header Authorization vencido no debe dar 401 acá.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_password_reset(serializer.validated_data['email'])

        return Response(
            {'detail': 'Si el correo está registrado, te enviamos un código de verificación.'},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    """
    Paso 2: valida el OTP y establece la nueva contraseña.
    No inicia sesión: el usuario debe hacer login después.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        confirm_password_reset(
            email=serializer.validated_data['email'],
            code=serializer.validated_data['code'],
            new_password=serializer.validated_data['new_password'],
        )

        return Response(
            {'detail': 'Contraseña actualizada. Ya podés iniciar sesión.'},
            status=status.HTTP_200_OK,
        )


class RefreshView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = TokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data, status=status.HTTP_200_OK)
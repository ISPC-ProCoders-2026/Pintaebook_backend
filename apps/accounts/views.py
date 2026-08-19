from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer

from .serializers import LoginSerializer, RegisterSerializer
from .services import generate_tokens, user_data


class RegisterView(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        tokens = generate_tokens(user)

        return Response(
            {
                **tokens,
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
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
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "role": None,
                },
            },
            status=status.HTTP_200_OK,
        )


class RefreshView(APIView):
    def post(self, request):
        serializer = TokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(user_data(request.user), status=status.HTTP_200_OK)


# Alternativa equivalente usando una vista basada en funcion, mas cercana al
# estilo explicito de FastAPI. Este ejemplo es solo pedagogico: las rutas
# actuales continuan usando RegisterView y LoginView.
#
# from rest_framework.decorators import api_view
#
# @api_view(['POST'])
# def register(request):
#     serializer = RegisterSerializer(data=request.data)
#     serializer.is_valid(raise_exception=True)
#     user = serializer.save()
#     tokens = generate_tokens(user)
#     return Response(
#         {**tokens, 'user': user_data(user)},
#         status=status.HTTP_201_CREATED,
#     )
#
# @api_view(['POST'])
# def login(request):
#     serializer = LoginSerializer(data=request.data)
#     serializer.is_valid(raise_exception=True)
#     user = authenticate(
#         request=request,
#         username=serializer.validated_data['email'],
#         password=serializer.validated_data['password'],
#     )
#     if user is None:
#         return Response(
#             {'detail': 'Credenciales invalidas.'},
#             status=status.HTTP_401_UNAUTHORIZED,
#         )
#     tokens = generate_tokens(user)
#     return Response(
#         {**tokens, 'user': user_data(user)},
#         status=status.HTTP_200_OK,
#     )
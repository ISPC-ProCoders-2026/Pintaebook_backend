from rest_framework_simplejwt.tokens import RefreshToken
from google.oauth2 import id_token
from google.auth.transport import requests
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed
from .models import User, Role


def generate_tokens(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    # Claim personalizado para que Angular y los permisos lean el rol sin ir a BD
    refresh['role'] = user.role.nombre_rol if user.role else None
    refresh['email'] = user.email

    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

def user_data(user):
    return {
        'id': str(user.id),
        'email': user.email,
        'first_name': user.first_name,  
        'last_name': user.last_name,
    }

def authenticate_google_user(google_jwt: str) -> dict:
    """
    Verifica el token de Google, obtiene o crea el usuario en PostgreSQL
    y genera los tokens JWT propios de Pinta Ebook.
    """
    try:
        # 1. Validar la firma contra los servidores de Google
        idinfo = id_token.verify_oauth2_token(
            google_jwt, 
            requests.Request(), 
            settings.GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise AuthenticationFailed('El token de Google es inválido o ha expirado.')

    # 2. Extraer datos del perfil
    email = idinfo.get('email')
    first_name = idinfo.get('given_name', '')
    last_name = idinfo.get('family_name', '')

    if not email:
        raise AuthenticationFailed('No se pudo obtener el email de la cuenta de Google.')

    # 3. Buscar o crear el usuario en la BD
    user = User.objects.filter(email=email).first()

    if not user:
        author_role = Role.objects.filter(nombre_rol='author').first()
        user = User.objects.create_user(
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=author_role
        )
        user.set_unusable_password()
        user.save()

    # 4. Generar nuestros tokens JWT locales
    tokens = generate_tokens(user)

    return {
        'tokens': tokens,
        'user': user
    }
    
import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from rest_framework_simplejwt.tokens import RefreshToken
from google.oauth2 import id_token
from google.auth.transport import requests
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from .models import User, Role, PasswordResetOTP

logger = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_INVALID_MESSAGE = 'El código es inválido o ha vencido.'


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


# --- Recuperación de contraseña por OTP ---

def _hash_otp(user: User, code: str) -> str:
    """HMAC del código, atado al usuario: un mismo código da hashes distintos."""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f'{user.id}:{code}'.encode(),
        hashlib.sha256,
    ).hexdigest()


def request_password_reset(email: str) -> None:
    """
    Genera un OTP y lo envía al correo de la cuenta.

    No informa si el correo existe (evita enumerar cuentas): si el usuario no
    existe, está inactivo o pidió otro código hace menos del cooldown, no hace
    nada. Un fallo al enviar el correo se registra pero no se propaga.
    """
    user = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
    if user is None:
        return

    last = user.password_reset_otps.order_by('-created_at').first()
    if last and timezone.now() - last.created_at < timedelta(seconds=OTP_RESEND_COOLDOWN_SECONDS):
        return

    code = f'{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}'
    with transaction.atomic():
        # Un solo código vigente por usuario: el nuevo invalida a los anteriores.
        user.password_reset_otps.filter(used_at__isnull=True).update(used_at=timezone.now())
        PasswordResetOTP.objects.create(
            user=user,
            code_hash=_hash_otp(user, code),
            expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
        )

    try:
        send_mail(
            subject='Tu código para recuperar la contraseña - Pinta Ebook',
            message=(
                f'Hola {user.first_name},\n\n'
                f'Tu código de verificación es: {code}\n\n'
                f'Vence en {OTP_TTL_MINUTES} minutos y solo se puede usar una vez.\n'
                'Si no pediste recuperar tu contraseña, ignorá este mensaje.\n'
            ),
            from_email=None,  # usa DEFAULT_FROM_EMAIL
            recipient_list=[user.email],
        )
    except Exception:
        logger.exception('No se pudo enviar el OTP de recuperación a %s', user.email)


def confirm_password_reset(email: str, code: str, new_password: str) -> None:
    """
    Valida el OTP y cambia la contraseña.

    Cualquier fallo del código (correo desconocido, código incorrecto, vencido,
    usado o bloqueado) responde con el mismo mensaje genérico.
    """
    invalid = ValidationError({'code': [OTP_INVALID_MESSAGE]})

    user = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
    if user is None:
        raise invalid

    matched = False
    # Los errores se levantan después del bloque atómico: si no, el rollback
    # desharía el conteo del intento fallido.
    with transaction.atomic():
        otp = (
            PasswordResetOTP.objects
            .select_for_update()
            .filter(user=user, used_at__isnull=True, expires_at__gt=timezone.now())
            .order_by('-created_at')
            .first()
        )
        if otp is not None and otp.attempts < OTP_MAX_ATTEMPTS:
            if hmac.compare_digest(otp.code_hash, _hash_otp(user, code.strip())):
                matched = True
                try:
                    validate_password(new_password, user)
                except DjangoValidationError as exc:
                    # El código era correcto: no se consume, puede reintentar.
                    raise ValidationError({'new_password': list(exc.messages)})
                user.set_password(new_password)
                user.save(update_fields=['password'])
                otp.used_at = timezone.now()
                otp.save(update_fields=['used_at'])
            else:
                otp.attempts += 1
                otp.save(update_fields=['attempts'])

    if not matched:
        raise invalid

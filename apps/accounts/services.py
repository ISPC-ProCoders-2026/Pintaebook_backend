from rest_framework_simplejwt.tokens import RefreshToken


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
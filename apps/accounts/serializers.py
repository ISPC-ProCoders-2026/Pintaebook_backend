from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Role, User


class UserSerializer(serializers.ModelSerializer):
    """Serializer de salida para representar la información pública del usuario."""
    role = serializers.CharField(source='role.nombre_rol', read_only=True)

    class Meta:
        model = User
        fields = (
            'id',
            'email',
            'first_name',
            'last_name',
            'role',
            'created_at',
        )
        read_only_fields = ('id', 'created_at')


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True) # Write only: no se muestra en la respuesta.


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, # Write only: no se muestra en la respuesta.
        min_length=8
    )

    class Meta:
        model = User
        fields = (
            'email',
            'password',
            'first_name',
            'last_name',
        )

    def validate_email(self, value):
        value = value.strip().lower()

        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                'El email ya está registrado.'
            )

        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        # Buscamos el rol AUTOR sembrado en la base de datos
        autor_role = Role.objects.filter(nombre_rol=Role.RoleName.AUTOR).first()
        validated_data['role'] = autor_role
        
        return User.objects.create_user(**validated_data)

class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True, error_messages={'required': 'El Id_token es obligatorio'}) #Token que envia el frontend luego de conectar con google.}


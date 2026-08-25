import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager

class Role(models.Model):
    """
    Tabla 'roles' según diagrama ER con valores estrictamente tipados.
    """
    class RoleName(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrador'
        AUTOR = 'AUTOR', 'Autor'

    nombre_rol = models.CharField(
        max_length=50,
        choices=RoleName.choices,
        unique=True,
        help_text="Rol restringido por sistema: ADMIN o AUTOR."
    )

    class Meta:
        db_table = 'roles'
        verbose_name = 'Rol'
        verbose_name_plural = 'Roles'

    def __str__(self):
        return self.get_nombre_rol_display()

class CustomUserManager(BaseUserManager):
    """Manager personalizado para autenticación vía email. Asistente interno del modelo que le enseña a Django cómo crear usuarios y superusuarios usando Email en lugar de Username (Panel de Django, no tiene que ver con el registro de usuarios normales.)."""
    
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('El email es obligatorio.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('El superusuario debe tener is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('El superusuario debe tener is_superuser=True.')

        # Asignamos el rol ADMIN si existe en la BD
        admin_role = Role.objects.filter(nombre_rol=Role.RoleName.ADMIN).first()
        if admin_role:
            extra_fields.setdefault('role', admin_role)

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=255, unique=True)
    first_name = models.CharField(max_length=150, blank=False, null=False)
    last_name = models.CharField(max_length=150, blank=False, null=False)
    
    role = models.ForeignKey(
        Role,
        on_delete=models.RESTRICT,
        db_column='role_id',
        null=True,
        blank=True,
        related_name='usuarios'
    )
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    username = None

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    class Meta:
        db_table = 'usuarios'

    def __str__(self):
        return f"{self.email} ({self.role.nombre_rol if self.role else 'Sin Rol'})"


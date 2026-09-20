from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CreditBalance

INITIAL_WELCOME_CREDITS = 100


# 1. El "@receiver" es la oreja. Dice: "Escuchá cuando el modelo de usuario (sender) se guarde (post_save)"
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_welcome_credit_balance(sender, instance, created, **kwargs):
    """ El objetivo de este Signal es que cada vez que se cree un usuario, este reciba creditos gratis para poder crear e-books, sin importar si la cuenta fue creada desde el front, desde el panel de administracion, etc. """
    
    # 2. "created" es un booleano (True/False). 
    # Solo es True si el usuario se está creando por PRIMERA vez (si solo se está editando, es False).
    if created:
        
        # 3. Como el usuario es nuevo, le creamos automáticamente su billetera con 100 créditos de regalo.
        CreditBalance.objects.create(
            usuario=instance,               # "instance" es el objeto del usuario que se acaba de registrar
            credits_available=INITIAL_WELCOME_CREDITS, # Los 100 créditos iniciales
        )
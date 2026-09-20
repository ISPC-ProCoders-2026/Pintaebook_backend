from django.db import transaction
from rest_framework.exceptions import APIException
from .models import CreditBalance

class InsufficientCreditsError(APIException):
    status_code = 402
    default_detail = 'Créditos insuficientes para realizar esta operación.'
    default_code = 'insufficient_credits'

class BillingService:
    @staticmethod
    def get_balance(user) -> int:
        balance, _ = CreditBalance.objects.get_or_create(usuario=user)
        return balance.credits_available

    @staticmethod
    @transaction.atomic
    def deduct_credits(user, amount: int) -> int:
        # Si es admin, bypass
        if getattr(user, 'role', None) and getattr(user.role, 'nombre_rol', '') == 'ADMIN':
            return BillingService.get_balance(user)

        balance = CreditBalance.objects.select_for_update().get(usuario=user)
        if balance.credits_available < amount:
            raise InsufficientCreditsError()

        balance.credits_available -= amount
        balance.save()
        return balance.credits_available
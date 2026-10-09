import logging

from django.db import DatabaseError, transaction
from rest_framework.exceptions import APIException

from infrastructure.mercadopago_client import MercadoPagoClient
from .models import CreditBalance, CreditPackage, EstadoTransaccion, PaymentTransaction

logger = logging.getLogger(__name__)


class InsufficientCreditsError(APIException):
    status_code = 402
    default_detail = 'Créditos insuficientes para realizar esta operación.'
    default_code = 'insufficient_credits'


class CreditPackageNotFoundError(APIException):
    status_code = 404
    default_detail = 'El paquete de créditos solicitado no existe.'
    default_code = 'credit_package_not_found'


class CreditPackageNotPurchasableError(APIException):
    status_code = 400
    default_detail = 'El paquete de créditos seleccionado no se puede comprar.'
    default_code = 'credit_package_not_purchasable'


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

    @staticmethod
    def create_checkout(user, paquete_id: int, gateway=None) -> dict:
        """
        Inicia el pago de un paquete de créditos:
        1. Busca el paquete y toma el monto de la base (nunca del cliente).
        2. Crea la preferencia de pago en Mercado Pago.
        3. Registra la transacción como 'pendiente'.
        Retorna {"init_point": <url de pago>}.

        `gateway` permite inyectar un cliente falso en los tests.
        """
        try:
            paquete = CreditPackage.objects.get(pk=paquete_id)
        except CreditPackage.DoesNotExist as exc:
            raise CreditPackageNotFoundError() from exc

        # transacciones_pagos exige monto > 0: se valida antes de llamar a la pasarela.
        if paquete.precio <= 0:
            raise CreditPackageNotPurchasableError()

        gateway = gateway or MercadoPagoClient()

        # La llamada de red va ANTES del insert y fuera de cualquier transacción de base:
        # si la pasarela falla, no queda ninguna fila; si el insert falla, solo queda
        # una preferencia sin pagar en Mercado Pago (inofensiva).
        preference = gateway.create_preference(
            title=paquete.nombre,
            unit_price=paquete.precio,
            external_reference=f'{user.pk}:{paquete.pk}',
        )

        try:
            PaymentTransaction.objects.create(
                usuario=user,
                paquete=paquete,
                id_transaccion_externa=preference['preference_id'],
                monto=paquete.precio,
                estado_transaccion=EstadoTransaccion.PENDIENTE,
            )
        except DatabaseError:
            logger.exception(
                "No se pudo registrar la transacción para la preferencia %s (usuario %s, paquete %s)",
                preference['preference_id'],
                user.pk,
                paquete.pk,
            )
            raise

        return {'init_point': preference['init_point']}
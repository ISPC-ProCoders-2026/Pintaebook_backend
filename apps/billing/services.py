import logging

from django.db import DatabaseError, transaction
from rest_framework.exceptions import APIException

from infrastructure.mercadopago_client import MercadoPagoClient
from .models import (
    CreditBalance,
    CreditPackage,
    EstadoTransaccion,
    PaymentTransaction,
)

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
        balance, _ = CreditBalance.objects.get_or_create(
            usuario=user
        )
        return balance.credits_available

    @staticmethod
    @transaction.atomic
    def deduct_credits(user, amount: int) -> int:
        """Descuenta créditos de forma atómica."""

        if amount <= 0:
            raise ValueError(
                'El importe a descontar debe ser positivo.'
            )

        if (
            getattr(user, 'role', None)
            and getattr(user.role, 'nombre_rol', '') == 'ADMIN'
        ):
            return BillingService.get_balance(user)

        balance = CreditBalance.objects.select_for_update().get(
            usuario=user
        )

        if balance.credits_available < amount:
            raise InsufficientCreditsError()

        balance.credits_available -= amount
        balance.save(update_fields=['credits_available'])

        return balance.credits_available

    @staticmethod
    @transaction.atomic
    def refund_credits(user, amount: int) -> int:
        """Reintegra créditos después de una operación fallida."""

        if amount <= 0:
            raise ValueError(
                'El importe a reintegrar debe ser positivo.'
            )

        if (
            getattr(user, 'role', None)
            and getattr(user.role, 'nombre_rol', '') == 'ADMIN'
        ):
            return BillingService.get_balance(user)

        balance = CreditBalance.objects.select_for_update().get(
            usuario=user
        )

        balance.credits_available += amount
        balance.save(update_fields=['credits_available'])

        return balance.credits_available

    @staticmethod
    def create_checkout(user, paquete_id: int, gateway=None) -> dict:
        """
        Inicia el pago de un paquete de créditos.

        1. Busca el paquete y toma el importe de la base de datos.
        2. Crea la preferencia de pago en Mercado Pago.
        3. Registra la transacción como pendiente.

        Retorna {"init_point": <url de pago>}.
        `gateway` permite inyectar un cliente falso en los tests.
        """
        try:
            paquete = CreditPackage.objects.get(pk=paquete_id)
        except CreditPackage.DoesNotExist as exc:
            raise CreditPackageNotFoundError() from exc

        if paquete.precio <= 0:
            raise CreditPackageNotPurchasableError()

        gateway = gateway or MercadoPagoClient()

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
                'No se pudo registrar la transacción para la preferencia '
                '%s (usuario %s, paquete %s)',
                preference['preference_id'],
                user.pk,
                paquete.pk,
            )
            raise

        return {'init_point': preference['init_point']}
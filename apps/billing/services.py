import logging
import uuid

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

# Estados de Mercado Pago que cierran un pago pendiente sin acreditar.
_NON_APPROVED_FINAL_STATUSES = {
    'rejected': EstadoTransaccion.FALLIDO,
    'cancelled': EstadoTransaccion.CANCELADO,
}


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
        2. Registra la transacción como pendiente (su ID será el
           external_reference que Mercado Pago nos devuelve en el webhook).
        3. Crea la preferencia de pago en Mercado Pago.
        4. Guarda el ID de preferencia en la transacción.

        Si la pasarela falla, la transacción queda 'fallido' (no queda basura
        pendiente) y se relanza el error.

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

        try:
            # id_transaccion_externa es NOT NULL y UNIQUE: se usa un valor
            # temporal hasta conocer el ID de preferencia real.
            tx = PaymentTransaction.objects.create(
                usuario=user,
                paquete=paquete,
                id_transaccion_externa=f'pendiente-{uuid.uuid4().hex}',
                monto=paquete.precio,
                estado_transaccion=EstadoTransaccion.PENDIENTE,
            )
        except DatabaseError:
            logger.exception(
                'No se pudo registrar la transacción (usuario %s, paquete %s)',
                user.pk,
                paquete.pk,
            )
            raise

        try:
            preference = gateway.create_preference(
                title=paquete.nombre,
                unit_price=paquete.precio,
                external_reference=str(tx.pk),
            )
        except Exception:
            # Compensación: la preferencia no se creó, no dejamos un
            # pendiente que nunca se va a pagar.
            tx.estado_transaccion = EstadoTransaccion.FALLIDO
            tx.save(update_fields=['estado_transaccion'])
            raise

        try:
            tx.id_transaccion_externa = preference['preference_id']
            tx.save(update_fields=['id_transaccion_externa'])
        except DatabaseError:
            logger.exception(
                'No se pudo guardar la preferencia %s en la transacción %s',
                preference['preference_id'],
                tx.pk,
            )
            raise

        return {'init_point': preference['init_point']}

    @staticmethod
    def process_payment_notification(payment_id: str, gateway=None) -> str:
        """
        Procesa una notificación de pago de Mercado Pago de forma idempotente.

        Devuelve una etiqueta del resultado (útil para logs y tests):
        'approved', 'already_processed', 'updated', 'ignored' o
        'amount_mismatch'. Los errores de la pasarela (502/503) se propagan
        para que Mercado Pago reintente la notificación.
        """
        gateway = gateway or MercadoPagoClient()

        # La llamada de red va FUERA de la transacción de BD: no queremos
        # filas bloqueadas mientras esperamos a Mercado Pago.
        payment = gateway.get_payment(payment_id)

        # external_reference = ID de nuestra PaymentTransaction (lo fija el checkout).
        try:
            transaction_id = int(payment['external_reference'])
        except (TypeError, ValueError):
            logger.warning(
                'Pago %s con external_reference no reconocido: %r',
                payment_id,
                payment['external_reference'],
            )
            return 'ignored'

        with transaction.atomic():
            # Bloqueamos la fila: si llegan dos webhooks iguales a la vez, el
            # segundo espera acá y, al entrar, ya la ve 'aprobado'.
            # of=('self',) bloquea solo transacciones_pagos, no el paquete.
            tx = (
                PaymentTransaction.objects
                .select_for_update(of=('self',))
                .select_related('paquete')
                .filter(pk=transaction_id)
                .first()
            )
            if tx is None:
                logger.warning(
                    'Pago %s referencia una transacción inexistente (%s)',
                    payment_id,
                    transaction_id,
                )
                return 'ignored'

            # Idempotencia: ya acreditada, no escribimos nada.
            if tx.estado_transaccion == EstadoTransaccion.APROBADO:
                logger.info(
                    'Pago %s ya procesado para la transacción %s',
                    payment_id,
                    tx.pk,
                )
                return 'already_processed'

            mp_status = payment['status']

            if mp_status == 'approved':
                if (
                    payment['transaction_amount'] != tx.monto
                    or payment['currency_id'] != MercadoPagoClient.CURRENCY_ID
                ):
                    logger.error(
                        'Pago %s: monto/moneda no coinciden '
                        '(MP: %s %s, esperado: %s %s). No se acredita.',
                        payment_id,
                        payment['transaction_amount'],
                        payment['currency_id'],
                        tx.monto,
                        MercadoPagoClient.CURRENCY_ID,
                    )
                    return 'amount_mismatch'

                tx.estado_transaccion = EstadoTransaccion.APROBADO
                tx.save(update_fields=['estado_transaccion'])
                BillingService._credit_purchase(
                    tx.usuario_id,
                    tx.paquete.cantidad_creditos,
                )
                logger.info(
                    'Pago %s aprobado: %s créditos para el usuario %s',
                    payment_id,
                    tx.paquete.cantidad_creditos,
                    tx.usuario_id,
                )
                return 'approved'

            # Rechazado/cancelado: solo cierra una fila pendiente.
            new_state = _NON_APPROVED_FINAL_STATUSES.get(mp_status)
            if new_state and tx.estado_transaccion == EstadoTransaccion.PENDIENTE:
                tx.estado_transaccion = new_state
                tx.save(update_fields=['estado_transaccion'])
                return 'updated'

            # pending / in_process / refunded / etc.: sin cambios.
            logger.info(
                "Pago %s con estado '%s' sin cambios para la transacción %s",
                payment_id,
                mp_status,
                tx.pk,
            )
            return 'ignored'

    @staticmethod
    def _credit_purchase(user_id, amount: int) -> None:
        """
        Suma los créditos comprados al saldo del usuario.

        Debe llamarse dentro de un transaction.atomic(). No reutiliza
        refund_credits porque ese método saltea a los ADMIN: una compra
        siempre debe acreditarse.
        """
        balance, _ = CreditBalance.objects.select_for_update().get_or_create(
            usuario_id=user_id
        )
        balance.credits_available += amount
        # last_updated va explícito: con update_fields, auto_now no se guarda solo.
        balance.save(update_fields=['credits_available', 'last_updated'])
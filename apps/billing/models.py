import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class CreditBalance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='credit_balance',
        db_column='usuario_id',
    )
    credits_available = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'balances_credito'

    def __str__(self):
        return f"{self.usuario.email} - {self.credits_available} créditos"


class EstadoTransaccion(models.TextChoices):
    """Estados posibles de un pago.

    Está a nivel de módulo (no dentro de PaymentTransaction) para que
    Meta.constraints pueda usarlo: una clase anidada no ve los nombres
    definidos en el cuerpo de la clase que la contiene.
    """

    PENDIENTE = 'pendiente', 'Pendiente'
    APROBADO = 'aprobado', 'Aprobado'
    FALLIDO = 'fallido', 'Fallido'
    REEMBOLSADO = 'reembolsado', 'Reembolsado'
    CANCELADO = 'cancelado', 'Cancelado'


class CreditPackage(models.Model):
    """Catálogo de paquetes de créditos que un usuario puede comprar."""

    # SERIAL (32 bits) según el diagrama. Se declara explícito para no
    # depender de DEFAULT_AUTO_FIELD (que podría generar BIGSERIAL).
    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100, unique=True)
    # IntegerField (y no PositiveIntegerField) porque el diagrama pide
    # CHECK > 0 y PositiveIntegerField ya agrega un CHECK >= 0 propio.
    cantidad_creditos = models.IntegerField()
    precio = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'paquetes_credito'
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad_creditos__gt=0),
                name='paquete_cantidad_creditos_positiva',
            ),
            models.CheckConstraint(
                condition=Q(precio__gte=0),
                name='paquete_precio_no_negativo',
            ),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.cantidad_creditos} créditos)"


class PaymentTransaction(models.Model):
    """Registro de cada intento de pago de un usuario por un paquete."""

    id = models.AutoField(primary_key=True)
    # Regla de negocio 6: al borrar el usuario se borran sus transacciones.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_transactions',
    )
    # RESTRICT en el diagrama: no se puede borrar un paquete con ventas.
    paquete = models.ForeignKey(
        CreditPackage,
        on_delete=models.PROTECT,
        related_name='payment_transactions',
    )
    # ID del pago en Mercado Pago. UNIQUE evita registrar dos veces el
    # mismo pago si el webhook llega repetido.
    id_transaccion_externa = models.CharField(max_length=255, unique=True)
    # Monto realmente cobrado (snapshot): no cambia si luego cambia el precio.
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    estado_transaccion = models.CharField(
        max_length=50,
        choices=EstadoTransaccion.choices,
    )
    # db_default: el DEFAULT lo define PostgreSQL (como pide el diagrama),
    # así también aplica a INSERTs que no pasan por el ORM.
    fecha = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = 'transacciones_pagos'
        constraints = [
            models.CheckConstraint(
                condition=Q(monto__gt=0),
                name='transaccion_monto_positivo',
            ),
            models.CheckConstraint(
                condition=Q(estado_transaccion__in=EstadoTransaccion.values),
                name='transaccion_estado_valido',
            ),
        ]

    def __str__(self):
        return f"{self.id_transaccion_externa} - {self.estado_transaccion}"
from rest_framework import serializers
from .models import CreditBalance, CreditPackage, PaymentTransaction


class CreditPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditPackage
        fields = ('id', 'nombre', 'cantidad_creditos', 'precio')
        read_only_fields = fields


class PackageSummarySerializer(serializers.ModelSerializer):
    """Resumen del paquete comprado (sin precio: el cobrado está en `monto`)."""

    class Meta:
        model = CreditPackage
        fields = ('id', 'nombre', 'cantidad_creditos')
        read_only_fields = fields


class PaymentTransactionSerializer(serializers.ModelSerializer):
    """Una fila del historial de compras. No expone `id_transaccion_externa`."""

    paquete = PackageSummarySerializer(read_only=True)
    estado = serializers.CharField(source='estado_transaccion', read_only=True)

    class Meta:
        model = PaymentTransaction
        fields = ('id', 'paquete', 'monto', 'estado', 'fecha')
        read_only_fields = fields


class CreditBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditBalance
        fields = ('credits_available', 'last_updated')
        read_only_fields = ('credits_available', 'last_updated')


class CheckoutRequestSerializer(serializers.Serializer):
    # max_value = máximo de un integer de PostgreSQL (la PK de paquetes_credito es de 32 bits)
    paquete_id = serializers.IntegerField(min_value=1, max_value=2147483647)
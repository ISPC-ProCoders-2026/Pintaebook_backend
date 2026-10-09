from rest_framework import serializers
from .models import CreditBalance


class CreditBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditBalance
        fields = ('credits_available', 'last_updated')
        read_only_fields = ('credits_available', 'last_updated')


class CheckoutRequestSerializer(serializers.Serializer):
    # max_value = máximo de un integer de PostgreSQL (la PK de paquetes_credito es de 32 bits)
    paquete_id = serializers.IntegerField(min_value=1, max_value=2147483647)
from rest_framework import serializers
from .models import CreditBalance


class CreditBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditBalance
        fields = ('credits_available', 'last_updated')
        read_only_fields = ('credits_available', 'last_updated')
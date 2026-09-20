from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import CreditBalance
from .serializers import CreditBalanceSerializer


class BillingBalanceView(APIView):
    """
    Retorna el saldo disponible de créditos y la fecha de última actualización
    para el usuario autenticado.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        balance, _ = CreditBalance.objects.get_or_create(usuario=request.user)
        serializer = CreditBalanceSerializer(balance)
        return Response(serializer.data)
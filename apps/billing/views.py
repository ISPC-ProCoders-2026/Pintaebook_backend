from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import CreditBalance
from .serializers import CheckoutRequestSerializer, CreditBalanceSerializer
from .services import BillingService


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


class BillingCheckoutView(APIView):
    """
    Inicia el pago de un paquete de créditos: crea la preferencia en Mercado Pago,
    registra la transacción como 'pendiente' y retorna la URL de pago (init_point)
    a la que el frontend debe redirigir al usuario.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CheckoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = BillingService.create_checkout(
            user=request.user,
            paquete_id=serializer.validated_data['paquete_id'],
        )
        return Response(result, status=status.HTTP_201_CREATED)
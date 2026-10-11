from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

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


class BillingWebhookView(APIView):
    """
    Webhook de Mercado Pago. Público: lo llama MP, no un usuario.
    No se confía en el cuerpo de la petición: solo se extrae el Payment ID y
    el servicio consulta a Mercado Pago el estado real del pago.
    """
    # Sin autenticación: si quedara el JWT global, un header ajeno daría 401.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        data = body.get('data') if isinstance(body.get('data'), dict) else {}
        params = request.query_params

        # MP manda el tipo y el id por query (?type=payment&data.id=123),
        # por body JSON, o con el formato viejo (?topic=payment&id=123).
        notification_type = body.get('type') or params.get('type') or params.get('topic')
        payment_id = str(data.get('id') or params.get('data.id') or params.get('id') or '')

        if notification_type != 'payment':
            return Response({'detail': 'Notificación ignorada.'}, status=status.HTTP_200_OK)

        # Este valor termina en la URL hacia MP: solo dígitos.
        if not payment_id.isdigit():
            return Response({'detail': 'Payment ID inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        BillingService.process_payment_notification(payment_id)
        return Response({'detail': 'OK'}, status=status.HTTP_200_OK)
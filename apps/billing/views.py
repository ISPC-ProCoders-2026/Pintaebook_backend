from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from .models import CreditBalance, CreditPackage
from .serializers import (
    CheckoutRequestSerializer,
    CreditBalanceSerializer,
    CreditPackageSerializer,
)
from .services import BillingService


class CreditPackageListView(APIView):
    """
    Catálogo de paquetes de créditos disponibles para comprar, del más barato
    al más caro. Son pocos, por eso se devuelve la lista completa sin paginar.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        packages = CreditPackage.objects.order_by('precio', 'id')
        return Response(CreditPackageSerializer(packages, many=True).data)


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
    Endpoint (Webhook) receptor de notificaciones automáticas de Mercado Pago.

    Objetivo:
    - Escuchar las actualizaciones de estado de pagos (aprobado, rechazado, etc.)
      enviadas directamente por los servidores de Mercado Pago en segundo plano.

    Funcionamiento y Seguridad:
    - Público / Sin JWT: Lo invoca Mercado Pago directamente, no un usuario autenticado.
    - Validación y anti-fraude: Nunca se confía ciegamente en el contenido recibido.
      Solo se extrae y valida el Payment ID. Luego, el servicio (`BillingService`)
      realiza una consulta directa a la API oficial de Mercado Pago para verificar
      el estado real de la transacción antes de impactar los cambios en el sistema.
    - Compatibilidad: Soporta los distintos formatos de notificación de MP
      (JSON body, query params modernos y formato legacy topic/id).
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
        notification_type = (
            body.get('type') or body.get('topic')
            or params.get('type') or params.get('topic')
        )
        # Formato IPN por body: {"resource": "123" o ".../merchant_orders/123", "topic": ...}
        resource = str(body.get('resource') or '').rstrip('/').rsplit('/', 1)[-1]
        resource_id = str(
            data.get('id') or params.get('data.id') or params.get('id') or resource or ''
        )

        if notification_type == 'payment':
            handler = BillingService.process_payment_notification
        elif notification_type in ('merchant_order', 'topic_merchant_order_wh'):
            # El aviso trae el ID de la orden, no el del pago.
            handler = BillingService.process_merchant_order_notification
        else:
            return Response({'detail': 'Notificación ignorada.'}, status=status.HTTP_200_OK)

        # Este valor termina en la URL hacia MP: solo dígitos.
        if not resource_id.isdigit():
            return Response({'detail': 'ID inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        handler(resource_id)
        return Response({'detail': 'OK'}, status=status.HTTP_200_OK)
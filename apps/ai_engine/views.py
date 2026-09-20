import logging
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.services import BillingService
from apps.content.services import update_content
from apps.ebooks.models import EbookMetadata
from infrastructure.ai_client import AIClient

from .serializers import AIGenerateRequestSerializer
from .services import log_ia_interaction

logger = logging.getLogger(__name__)

# Costo fijo para refinamiento de secciones individuales
SECTION_REFINEMENT_COST = 10


class AIGenerateView(APIView):
    """
    Endpoint POST /api/ai/generate/:
    Valida ownership -> Verifica créditos -> Infiere con LLM ->
    Descuenta créditos -> Persiste HTML en Mongo -> Audita tokens.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AIGenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ebook_id = data['ebook_id']
        chapter_id = data['chapter_id']
        section_id = data['section_id']
        prompt = data['prompt']
        model_override = data.get('model') or None

        # 1. Validar propiedad del libro en PostgreSQL (404 si es ajeno)
        get_object_or_404(EbookMetadata, id=ebook_id, author=request.user)

        # 2. Comprobación preventiva de saldo
        current_balance = BillingService.get_balance(request.user)
        is_admin = getattr(request.user, 'role', None) and getattr(request.user.role, 'nombre_rol', '') == 'ADMIN'

        if not is_admin and current_balance < SECTION_REFINEMENT_COST:
            return Response(
                {
                    'error': {
                        'code': 'INSUFFICIENT_CREDITS',
                        'message': 'No cuentas con suficientes créditos para generar este contenido.',
                        'credits_required': SECTION_REFINEMENT_COST,
                        'credits_available': current_balance,
                    }
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        # 3. Invocar inferencia en OpenRouter
        ai_client = AIClient()
        ai_result = ai_client.generate_content(
            prompt=prompt,
            model=model_override,
        )

        generated_html = ai_result['html']
        tokens_used = ai_result['tokens_used']
        provider = ai_result['provider']
        resolved_model = ai_result['model']

        # 4. Débito atómico en PostgreSQL
        remaining_balance = BillingService.deduct_credits(request.user, SECTION_REFINEMENT_COST)

        # 5. Persistencia del contenido en MongoDB Atlas
        update_content(
            ebook_id=ebook_id,
            sections=[
                {
                    'chapter_id': chapter_id,
                    'section_id': section_id,
                    'html': generated_html,
                }
            ],
        )

        # 6. Registro de auditoría en MongoDB Atlas
        log_ia_interaction(
            user_id=request.user.id,
            ebook_id=ebook_id,
            section_id=section_id,
            provider=provider,
            model=resolved_model,
            prompt=prompt,
            tokens_used=tokens_used,
        )

        # 7. Respuesta estructurada al frontend
        return Response(
            {
                'ebook_id': str(ebook_id),
                'chapter_id': str(chapter_id),
                'section_id': str(section_id),
                'generated_html': generated_html,
                'tokens_consumed': tokens_used,
                'credits_debited': 0 if is_admin else SECTION_REFINEMENT_COST,
                'credits_available': remaining_balance,
            },
            status=status.HTTP_200_OK,
        )
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ebooks.models import EbookMetadata

from . import services
from .serializers import ContentPatchSerializer


class EbookContentView(APIView):
    permission_classes = [IsAuthenticated]

    def _check_ownership(self, request, ebook_id):
        # Un libro ajeno o inexistente responde 404 (no revela que existe).
        get_object_or_404(EbookMetadata, id=ebook_id, author=request.user)

    def get(self, request, ebook_id):
        self._check_ownership(request, ebook_id)
        return Response(services.get_content(ebook_id))

    def patch(self, request, ebook_id):
        self._check_ownership(request, ebook_id)

        serializer = ContentPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = services.update_content(
            ebook_id,
            sections=serializer.validated_data.get('sections'),
            chapters_order=serializer.validated_data.get('chapters_order'),
        )
        return Response(result)
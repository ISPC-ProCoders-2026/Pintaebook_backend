from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from . import services
from .models import EbookMetadata
from .serializers import EbookSerializer


class EbookViewSet(viewsets.ModelViewSet):
    serializer_class = EbookSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Solo los libros del autor autenticado: uno ajeno responde 404.
        return EbookMetadata.objects.filter(author=self.request.user)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def perform_destroy(self, instance):
        services.delete_ebook(instance)
from rest_framework import filters, viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from . import services
from .models import EbookMetadata
from .serializers import EbookSerializer


class EbookViewSet(viewsets.ModelViewSet):
    serializer_class = EbookSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    
    # Búsqueda avanzada combinada: busca coincidencias en title o description
    search_fields = ['title', 'description']
    
    # Ordenamiento parametrizado
    ordering_fields = ['created_at', 'updated_at', 'title']
    ordering = ['-created_at']

    def get_queryset(self):
        # Admite lectura completa para ADMIN o solo libros del autor autenticado
        user = self.request.user
        if hasattr(user, 'role') and user.role and user.role.nombre_rol == 'ADMIN':
            queryset = EbookMetadata.objects.all()
        else:
            queryset = EbookMetadata.objects.filter(author=user)
        
        # Filtros adicionales por query params (ej. /api/ebooks/?created_after=2026-01-01)
        created_after = self.request.query_params.get('created_after')
        if created_after:
            queryset = queryset.filter(created_at__date__gte=created_after)
            
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def perform_destroy(self, instance):
        services.delete_ebook(instance)
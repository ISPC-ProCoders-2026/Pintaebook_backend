from rest_framework import serializers

from . import services
from .models import EbookMetadata


class EbookSerializer(serializers.ModelSerializer):
    """Serializer del libro. El ebook_id y el autor nunca vienen del cliente."""

    ebook_id = serializers.UUIDField(source='id', read_only=True)

    class Meta:
        model = EbookMetadata
        fields = ('ebook_id', 'title', 'description', 'created_at', 'updated_at')
        read_only_fields = ('ebook_id', 'created_at', 'updated_at')

    def create(self, validated_data):
        return services.create_ebook(**validated_data)

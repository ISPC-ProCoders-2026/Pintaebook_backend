from rest_framework import serializers
from .models import EbookMetadata
from . import services


class EbookSerializer(serializers.ModelSerializer):
    """Permite recibir prompt_idea y quantity_chapters (que solo intervienen durante la creación) y exponer credits_available en la respuesta"""
    
    ebook_id = serializers.UUIDField(source='id', read_only=True)
    prompt_idea = serializers.CharField(
        write_only=True, required=False, allow_blank=True, default=''
    )
    quantity_chapters = serializers.IntegerField(
        write_only=True, required=False, default=3, min_value=1, max_value=10
    )
    credits_available = serializers.IntegerField(read_only=True)

    class Meta:
        model = EbookMetadata
        fields = (
            'ebook_id',
            'title',
            'description',
            'prompt_idea',
            'quantity_chapters',
            'credits_available',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('ebook_id', 'credits_available', 'created_at', 'updated_at')

    def create(self, validated_data):
        return services.create_ebook(**validated_data)
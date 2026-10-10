from rest_framework import serializers

from . import services
from .models import EbookMetadata


class EbookSerializer(serializers.ModelSerializer):
    """Serializador para crear y consultar los metadatos de un ebook."""

    ebook_id = serializers.UUIDField(
        source='id',
        read_only=True,
    )

    prompt_idea = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        default='',
    )

    quantity_chapters = serializers.IntegerField(
        write_only=True,
        required=False,
        default=3,
        min_value=1,
        max_value=10,
    )

    credits_available = serializers.IntegerField(read_only=True)

    class Meta:
        model = EbookMetadata
        fields = (
            'ebook_id',
            'title',
            'description',
            'status',
            'prompt_idea',
            'quantity_chapters',
            'credits_available',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'ebook_id',
            'status',
            'credits_available',
            'created_at',
            'updated_at',
        )

    def create(self, validated_data):
        author = validated_data.pop('author', None)

        if author is None:
            raise serializers.ValidationError({
                'author': 'El autor es obligatorio para crear un ebook.',
            })

        return services.create_ebook(
            author=author,
            **validated_data,
        )
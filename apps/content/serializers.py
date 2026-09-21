from rest_framework import serializers

MAX_HTML_LENGTH = 500_000  # protege el límite de 16 MB del documento en Mongo


class SectionUpdateSerializer(serializers.Serializer):
    chapter_id = serializers.UUIDField()
    section_id = serializers.UUIDField()
    html = serializers.CharField(
        allow_blank=True, trim_whitespace=False, max_length=MAX_HTML_LENGTH
    )


class ContentPatchSerializer(serializers.Serializer):
    sections = SectionUpdateSerializer(many=True, required=False)
    chapters_order = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=False
    )

    def validate(self, attrs):
        if not attrs.get('sections') and 'chapters_order' not in attrs:
            raise serializers.ValidationError(
                'Enviá al menos "sections" o "chapters_order".'
            )
        return attrs
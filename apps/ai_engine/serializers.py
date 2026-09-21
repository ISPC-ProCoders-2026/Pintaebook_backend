from rest_framework import serializers


class AIGenerateRequestSerializer(serializers.Serializer):
    ebook_id = serializers.UUIDField()
    chapter_id = serializers.UUIDField()
    section_id = serializers.UUIDField()
    prompt = serializers.CharField(min_length=5, max_length=2000)
    model = serializers.CharField(required=False, allow_blank=True, max_length=100)
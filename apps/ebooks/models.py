import uuid

from django.conf import settings
from django.db import models


class EbookMetadata(models.Model):
    """Metadatos relacionales del libro; el contenido vive en MongoDB."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.RESTRICT,
        related_name='ebooks',
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ebook_metadata'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.id})"

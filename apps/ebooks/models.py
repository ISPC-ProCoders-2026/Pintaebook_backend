import uuid
from django.db import models
from django.conf import settings


class EbookMetadata(models.Model):
    STATUS_CHOICES = (
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ebooks'
    )
    titulo = models.CharField(max_length=255)
    url_portada = models.URLField(max_length=500, blank=True, null=True)
    isbn = models.CharField(max_length=20, unique=True, blank=True, null=True) #ISBN es para almacenar el código identificador único del libro electrónico, en este mvp no hace falta omitirlo pero tampoco hay que preocuparse por su validez de los numeros.
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PROCESSING')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ebook_metadata'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"{self.titulo} - {self.usuario.email}"
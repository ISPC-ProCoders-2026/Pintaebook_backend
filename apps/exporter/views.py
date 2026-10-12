import json

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.views import APIView

from apps.content import services as content_services
from apps.ebooks.models import EbookMetadata

from .services import EbookNotReadyError, build_epub


class EpubRenderer(BaseRenderer):
    """
    Permite que un cliente pida `Accept: application/epub+zip` sin recibir 406.
    El archivo se devuelve ya armado (HttpResponse); si hay un error (404, 409...)
    se serializa como JSON igual que en el resto de la API.
    """
    media_type = 'application/epub+zip'
    format = 'epub'
    charset = None
    render_style = 'binary'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        return json.dumps(data).encode('utf-8')


class EbookEpubExportView(APIView):
    """
    GET /api/ebooks/<ebook_id>/export/epub/

    Devuelve el e-book como archivo .epub (descarga). Gratis. Solo el autor del
    libro puede exportarlo y solo si está COMPLETED.
    """
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer, EpubRenderer]

    def get(self, request, ebook_id):
        # Un libro ajeno o inexistente responde 404 (no revela que existe).
        ebook = get_object_or_404(
            EbookMetadata.objects.select_related('author'),
            id=ebook_id,
            author=request.user,
        )

        if ebook.status != 'COMPLETED':
            raise EbookNotReadyError()

        content = content_services.get_content(ebook.id)
        epub_bytes = build_epub(ebook, content)

        filename = f'{slugify(ebook.title) or "ebook"}.epub'
        response = HttpResponse(epub_bytes, content_type='application/epub+zip')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

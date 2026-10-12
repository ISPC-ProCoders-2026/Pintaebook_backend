import io
import uuid
import zipfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.test import APITestCase

from apps.ebooks.models import EbookMetadata

from .services import EbookWithoutChaptersError, _to_xhtml, build_epub

User = get_user_model()

GET_CONTENT = 'apps.exporter.views.content_services.get_content'


def _content(ebook_id):
    return {
        'ebook_id': str(ebook_id),
        'chapters': [
            {
                'id': str(uuid.uuid4()),
                'title': 'Capítulo 1: Introducción',
                'sections': [
                    {'id': str(uuid.uuid4()), 'title': 'Conceptos base',
                     'html': '<p>Hola <b>mundo</b><br>línea dos</p>'},
                    {'id': str(uuid.uuid4()), 'title': 'Más cosas',
                     'html': '<p>Ñandú & compañía</p><script>alert(1)</script>'},
                ],
            },
            {
                'id': str(uuid.uuid4()),
                'title': 'Capítulo 2',
                'sections': [
                    {'id': str(uuid.uuid4()), 'title': 'Final', 'html': '<p>Fin</p>'},
                ],
            },
        ],
    }


class EpubExportApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='autor@test.com', password='Clave-Segura-123',
            first_name='Ana', last_name='Autora',
        )
        self.other = User.objects.create_user(
            email='otro@test.com', password='Clave-Segura-123',
            first_name='Otto', last_name='Otro',
        )
        self.ebook = EbookMetadata.objects.create(
            author=self.user, title='Mi Libro de Prueba', description='Una descripción',
            status='COMPLETED',
        )
        self.url = f'/api/ebooks/{self.ebook.id}/export/epub/'
        self.client.force_authenticate(user=self.user)

    def test_exporta_epub_valido(self):
        with patch(GET_CONTENT, return_value=_content(self.ebook.id)):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/epub+zip')
        self.assertIn('attachment; filename="mi-libro-de-prueba.epub"', response['Content-Disposition'])

        archive = zipfile.ZipFile(io.BytesIO(response.content))
        self.assertIsNone(archive.testzip())
        # El primer archivo debe ser 'mimetype' y sin comprimir (requisito de EPUB).
        first = archive.infolist()[0]
        self.assertEqual(first.filename, 'mimetype')
        self.assertEqual(first.compress_type, zipfile.ZIP_STORED)
        self.assertEqual(archive.read('mimetype'), b'application/epub+zip')

        names = archive.namelist()
        self.assertIn('META-INF/container.xml', names)
        self.assertTrue(any(n.endswith('chapter_1.xhtml') for n in names))
        self.assertTrue(any(n.endswith('chapter_2.xhtml') for n in names))

    def test_el_epub_contiene_titulo_autor_y_contenido(self):
        with patch(GET_CONTENT, return_value=_content(self.ebook.id)):
            response = self.client.get(self.url)

        archive = zipfile.ZipFile(io.BytesIO(response.content))
        opf = archive.read(next(n for n in archive.namelist() if n.endswith('.opf'))).decode('utf-8')
        self.assertIn('Mi Libro de Prueba', opf)
        self.assertIn('Ana Autora', opf)
        self.assertIn(str(self.ebook.id), opf)

        chapter = archive.read(next(n for n in archive.namelist() if n.endswith('chapter_1.xhtml'))).decode('utf-8')
        self.assertIn('Capítulo 1: Introducción', chapter)
        self.assertIn('Conceptos base', chapter)
        self.assertIn('<br/>', chapter)          # XHTML bien formado
        self.assertNotIn('<script', chapter)     # sanitizado
        self.assertIn('Ñandú &amp; compañía', chapter)

    def test_sin_autenticar_retorna_401(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_libro_ajeno_retorna_404(self):
        self.client.force_authenticate(user=self.other)
        with patch(GET_CONTENT) as mock_content:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_content.assert_not_called()

    def test_libro_inexistente_retorna_404(self):
        response = self.client.get(f'/api/ebooks/{uuid.uuid4()}/export/epub/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_libro_en_proceso_retorna_409(self):
        for state in ('PROCESSING', 'FAILED'):
            EbookMetadata.objects.filter(pk=self.ebook.pk).update(status=state)
            with patch(GET_CONTENT) as mock_content:
                response = self.client.get(self.url)
            self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, state)
            mock_content.assert_not_called()

    def test_libro_sin_capitulos_retorna_409(self):
        with patch(GET_CONTENT, return_value={'ebook_id': str(self.ebook.id), 'chapters': []}):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_libro_sin_contenido_en_mongo_retorna_404(self):
        with patch(GET_CONTENT, side_effect=NotFound('El libro no tiene contenido inicializado.')):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_accept_epub_no_da_406(self):
        with patch(GET_CONTENT, return_value=_content(self.ebook.id)):
            response = self.client.get(self.url, HTTP_ACCEPT='application/epub+zip')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_error_con_accept_epub_sigue_siendo_json(self):
        EbookMetadata.objects.filter(pk=self.ebook.pk).update(status='PROCESSING')
        response = self.client.get(self.url, HTTP_ACCEPT='application/epub+zip')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn(b'detail', response.content)


class BuildEpubUnitTests(SimpleTestCase):
    def test_to_xhtml_cierra_etiquetas_y_escapa(self):
        out = _to_xhtml('<p>uno<br>dos</p><p>a &amp; b</p>')
        self.assertIn('<br/>', out)
        self.assertIn('a &amp; b', out)

    def test_to_xhtml_vacio(self):
        self.assertEqual(_to_xhtml(''), '')
        self.assertEqual(_to_xhtml('   '), '')

    def test_to_xhtml_quita_imagenes_sin_recurso(self):
        out = _to_xhtml('<p>antes <img src="x.png"> después</p>')
        self.assertNotIn('<img', out)
        self.assertIn('antes', out)
        self.assertIn('después', out)

    def test_to_xhtml_envuelve_el_contenido_en_un_div(self):
        out = _to_xhtml('solo texto')
        self.assertTrue(out.startswith('<div class="section">'))
        self.assertIn('solo texto', out)

    def test_to_xhtml_texto_suelto_y_caracteres_invalidos(self):
        out = _to_xhtml('texto suelto \x00 <b>negrita</b> final')
        self.assertIn('texto suelto', out)
        self.assertNotIn('\x00', out)
        self.assertIn('<b>negrita</b> final', out)

    def test_build_epub_sin_capitulos_lanza_error(self):
        class Ebook:
            id = uuid.uuid4()
            title = 'X'
            description = ''
            author = type('U', (), {'first_name': '', 'last_name': '', 'email': 'a@a.com'})()

        with self.assertRaises(EbookWithoutChaptersError):
            build_epub(Ebook(), {'chapters': []})

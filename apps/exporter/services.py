import html
import io
import logging
import re

from ebooklib import epub
from lxml import html as lxml_html
from rest_framework.exceptions import APIException

from apps.content.services import sanitize_html

logger = logging.getLogger(__name__)

LANGUAGE = 'es'

# Caracteres de control que XML 1.0 no admite: romperían el XHTML del EPUB.
_INVALID_XML_CHARS = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f]')

BOOK_CSS = """
body { font-family: serif; line-height: 1.5; margin: 5%; }
h1 { font-size: 1.8em; margin: 1em 0 0.6em; }
h2 { font-size: 1.3em; margin: 1.4em 0 0.5em; }
p { margin: 0 0 0.8em; text-align: justify; }
img { max-width: 100%; }
"""


class EbookNotReadyError(APIException):
    status_code = 409
    default_detail = 'El e-book todavía no está terminado: solo se pueden exportar e-books completados.'
    default_code = 'ebook_not_ready'


class EbookWithoutChaptersError(APIException):
    status_code = 409
    default_detail = 'El e-book no tiene capítulos para exportar.'
    default_code = 'ebook_without_chapters'


def _clean_text(value) -> str:
    return _INVALID_XML_CHARS.sub('', str(value or ''))


def _to_xhtml(raw_html: str) -> str:
    """
    Convierte el HTML de una sección en XHTML bien formado.

    1. Se sanitiza otra vez (el contenido podría haberse guardado sin pasar por
       el sanitizador) y se quitan caracteres inválidos para XML.
    2. Se parsea con lxml (tolera HTML5, etiquetas sin cerrar, etc.) y se
       reserializa como XML: <br> pasa a <br/>.
    """
    cleaned = _clean_text(sanitize_html(_clean_text(raw_html))).strip()
    if not cleaned:
        return ''

    try:
        # create_parent envuelve el fragmento en un <div> para soportar varios
        # elementos de primer nivel y texto suelto.
        fragment = lxml_html.fragment_fromstring(cleaned, create_parent='div')

        # Las imágenes apuntarían a archivos que no existen dentro del EPUB
        # (recursos rotos). Por ahora no se embeben: se quitan.
        for image in list(fragment.iter('img')):
            image.drop_tree()

        # tostring(child) incluye el texto que sigue a cada elemento (tail).
        inner = html.escape(fragment.text or '') + ''.join(
            lxml_html.tostring(child, method='xml', encoding='unicode')
            for child in fragment
        )
        return f'<div class="section">{inner}</div>'
    except Exception:  # noqa: BLE001 - un HTML raro no debe tumbar la exportación
        logger.warning('HTML de sección no parseable; se exporta como texto plano.')
        return f'<div class="section"><p>{html.escape(cleaned)}</p></div>'


def _author_name(user) -> str:
    full_name = f'{user.first_name} {user.last_name}'.strip()
    return full_name or user.email


def build_epub(ebook, content: dict) -> bytes:
    """
    Genera un EPUB 3 en memoria a partir de un EbookMetadata y su árbol de
    contenido (apps.content.services.get_content).

    Estructura: 1 capítulo del e-book = 1 archivo XHTML del EPUB, con sus
    secciones como subtítulos. La tabla de contenidos incluye capítulos y
    secciones.
    """
    chapters = content.get('chapters') or []
    if not chapters:
        raise EbookWithoutChaptersError()

    book = epub.EpubBook()
    book.set_identifier(f'urn:uuid:{ebook.id}')
    book.set_title(_clean_text(ebook.title))
    book.set_language(LANGUAGE)
    book.add_author(_author_name(ebook.author))
    if ebook.description:
        book.add_metadata('DC', 'description', _clean_text(ebook.description))

    style = epub.EpubItem(
        uid='style',
        file_name='style/book.css',
        media_type='text/css',
        content=BOOK_CSS,
    )
    book.add_item(style)

    spine_items = []
    toc = []

    for chapter_number, chapter in enumerate(chapters, start=1):
        chapter_title = _clean_text(chapter.get('title')) or f'Capítulo {chapter_number}'
        file_name = f'chapter_{chapter_number}.xhtml'

        parts = [f'<h1>{html.escape(chapter_title)}</h1>']
        section_links = []

        for section_number, section in enumerate(chapter.get('sections') or [], start=1):
            section_title = _clean_text(section.get('title'))
            anchor = f'sec-{chapter_number}-{section_number}'
            if section_title:
                parts.append(f'<h2 id="{anchor}">{html.escape(section_title)}</h2>')
                section_links.append(
                    epub.Link(f'{file_name}#{anchor}', section_title, f'{anchor}')
                )
            parts.append(_to_xhtml(section.get('html', '')))

        item = epub.EpubHtml(title=chapter_title, file_name=file_name, lang=LANGUAGE)
        item.content = ''.join(parts)
        item.add_item(style)
        book.add_item(item)
        spine_items.append(item)

        if section_links:
            toc.append((epub.Section(chapter_title, href=file_name), section_links))
        else:
            toc.append(item)

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav'] + spine_items

    buffer = io.BytesIO()
    epub.write_epub(buffer, book)
    return buffer.getvalue()

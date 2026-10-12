from django.urls import path

from .views import EbookEpubExportView

urlpatterns = [
    path('ebooks/<uuid:ebook_id>/export/epub/', EbookEpubExportView.as_view(), name='ebook-export-epub'),
]

from django.urls import path

from .views import EbookContentView

urlpatterns = [
    path('ebooks/<uuid:ebook_id>/content/', EbookContentView.as_view(), name='ebook-content'),
]
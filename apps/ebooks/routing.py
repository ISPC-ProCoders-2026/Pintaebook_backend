from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/ebooks/(?P<ebook_id>[0-9a-fA-F-]+)/progress/$", consumers.EbookProgressConsumer.as_asgi()),
]
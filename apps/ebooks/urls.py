from rest_framework.routers import SimpleRouter

from .views import EbookViewSet

router = SimpleRouter()
router.register(r'ebooks', EbookViewSet, basename='ebook')

urlpatterns = router.urls
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from pymongo.errors import PyMongoError
from rest_framework import status
from rest_framework.test import APITestCase

from .models import EbookMetadata

User = get_user_model()


class EbookApiTests(APITestCase):
    def setUp(self):
        # Mongo se simula: los tests no dependen de una instancia real.
        patcher = patch('apps.ebooks.services.get_mongo_db')
        mock_get_db = patcher.start()
        self.addCleanup(patcher.stop)
        self.collection = MagicMock()
        mock_get_db.return_value.__getitem__.return_value = self.collection

        self.user = User.objects.create_user(
            email='autor@test.com', password='Clave-Segura-123',
            first_name='Ana', last_name='Autora',
        )
        self.other = User.objects.create_user(
            email='otro@test.com', password='Clave-Segura-123',
            first_name='Otto', last_name='Otro',
        )
        self.url = '/api/ebooks/'
        self.client.force_authenticate(user=self.user)

    def test_crear_ebook_inicializa_documento_en_mongo(self):
        response = self.client.post(self.url, {'title': 'Mi libro'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ebook = EbookMetadata.objects.get()
        self.assertEqual(ebook.author, self.user)
        self.assertEqual(response.data['ebook_id'], str(ebook.id))

        doc = self.collection.insert_one.call_args.args[0]
        self.assertEqual(doc['_id'], str(ebook.id))
        self.assertEqual(doc['chapters'], [])

    def test_crear_ebook_hace_rollback_si_mongo_falla(self):
        self.collection.insert_one.side_effect = PyMongoError('Mongo caÃdo')

        response = self.client.post(self.url, {'title': 'Mi libro'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(EbookMetadata.objects.count(), 0)

    def test_listar_devuelve_solo_libros_propios(self):
        EbookMetadata.objects.create(author=self.user, title='Propio')
        EbookMetadata.objects.create(author=self.other, title='Ajeno')

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([e['title'] for e in response.data], ['Propio'])

    def test_detalle_de_libro_ajeno_devuelve_404(self):
        ajeno = EbookMetadata.objects.create(author=self.other, title='Ajeno')

        response = self.client.get(f'{self.url}{ajeno.id}/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_eliminar_borra_en_postgres_y_mongo(self):
        ebook = EbookMetadata.objects.create(author=self.user, title='Propio')
        ebook_id = str(ebook.id)

        response = self.client.delete(f'{self.url}{ebook_id}/')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(EbookMetadata.objects.count(), 0)
        self.collection.delete_one.assert_called_once_with({'_id': ebook_id})

    def test_eliminar_con_mongo_caido_igual_borra_el_libro(self):
        ebook = EbookMetadata.objects.create(author=self.user, title='Propio')
        self.collection.delete_one.side_effect = PyMongoError('Mongo caÃdo')

        response = self.client.delete(f'{self.url}{ebook.id}/')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(EbookMetadata.objects.count(), 0)

    def test_requiere_autenticacion(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
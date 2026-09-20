import json
from unittest.mock import MagicMock, patch
from django.contrib.auth import get_user_model
from pymongo.errors import PyMongoError
from rest_framework import status
from rest_framework.test import APITestCase

from apps.billing.models import CreditBalance
from .models import EbookMetadata

User = get_user_model()


class EbookApiTests(APITestCase):
    def setUp(self):
        patcher = patch('apps.ebooks.services.get_mongo_db')
        mock_get_db = patcher.start()
        self.addCleanup(patcher.stop)
        self.collection = MagicMock()
        mock_get_db.return_value.__getitem__.return_value = self.collection

        self.user = User.objects.create_user(
            email='autor@test.com',
            password='Clave-Segura-123',
            first_name='Ana',
            last_name='Autora',
        )
        self.other = User.objects.create_user(
            email='otro@test.com',
            password='Clave-Segura-123',
            first_name='Otto',
            last_name='Otro',
        )
        self.url = '/api/ebooks/'
        self.client.force_authenticate(user=self.user)

    @patch('apps.ebooks.services.AIClient')
    @patch('apps.ebooks.services.log_ia_interaction')
    def test_crear_ebook_genera_contenido_y_debit_creditos(self, mock_log, mock_ai):
        mock_ai_instance = MagicMock()
        mock_ai_instance.generate_content.return_value = {
            'html': json.dumps([{"title": "Cap 1", "sections": [{"title": "Sec 1", "html": "<p>Contenido</p>"}]}]),
            'tokens_used': 200,
            'provider': 'openrouter',
            'model': 'test-model',
        }
        mock_ai.return_value = mock_ai_instance

        payload = {
            'title': 'Mi libro con IA',
            'prompt_idea': 'Nutrición deportiva y recetas',
            'quantity_chapters': 1,
        }
        response = self.client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ebook = EbookMetadata.objects.get()
        self.assertEqual(ebook.author, self.user)
        self.assertEqual(response.data['ebook_id'], str(ebook.id))
        self.assertEqual(response.data['credits_available'], 0)  # 100 iniciales - 100 costo de creación

        balance = CreditBalance.objects.get(usuario=self.user)
        self.assertEqual(balance.credits_available, 0)

        doc = self.collection.insert_one.call_args[0][0]
        self.assertEqual(doc['_id'], str(ebook.id))
        self.assertEqual(doc['ebook_id'], str(ebook.id))
        self.assertEqual(len(doc['chapters']), 1)

    def test_crear_ebook_sin_saldo_retorna_402(self):
        balance = CreditBalance.objects.get(usuario=self.user)
        balance.credits_available = 20  # Saldo insuficiente frente a 100
        balance.save()

        response = self.client.post(self.url, {'title': 'Libro Rechazado'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(EbookMetadata.objects.count(), 0)

    @patch('apps.ebooks.services.AIClient')
    @patch('apps.ebooks.services.log_ia_interaction')
    def test_crear_ebook_hace_rollback_si_mongo_falla(self, mock_log, mock_ai):
        mock_ai_instance = MagicMock()
        mock_ai_instance.generate_content.return_value = {
            'html': json.dumps([{"title": "Cap 1", "sections": [{"title": "Sec 1", "html": "<p>Contenido</p>"}]}]),
            'tokens_used': 100,
            'provider': 'openrouter',
            'model': 'test-model',
        }
        mock_ai.return_value = mock_ai_instance

        self.collection.insert_one.side_effect = PyMongoError('Mongo caído')

        response = self.client.post(self.url, {'title': 'Mi libro'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(EbookMetadata.objects.count(), 0)

        balance = CreditBalance.objects.get(usuario=self.user)
        self.assertEqual(balance.credits_available, 100)

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
        self.collection.delete_one.side_effect = PyMongoError('Mongo caído')

        response = self.client.delete(f'{self.url}{ebook.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(EbookMetadata.objects.count(), 0)

    def test_requiere_autenticacion(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
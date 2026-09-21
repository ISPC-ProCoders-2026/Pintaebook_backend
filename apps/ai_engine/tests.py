import uuid
from unittest.mock import MagicMock, patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from pymongo.errors import PyMongoError
from rest_framework import status
from rest_framework.test import APITestCase

from apps.billing.models import CreditBalance
from apps.ebooks.models import EbookMetadata
from .services import log_ia_interaction

User = get_user_model()


class PromptLogsTests(TestCase):
    def setUp(self):
        patcher = patch('apps.ai_engine.services.get_mongo_db')
        mock_get_db = patcher.start()
        self.addCleanup(patcher.stop)

        self.collection = MagicMock()
        mock_get_db.return_value.__getitem__.return_value = self.collection

        self.user_id = str(uuid.uuid4())
        self.ebook_id = str(uuid.uuid4())

    def test_log_ia_interaction_persiste_documento_correctamente(self):
        fake_inserted_id = uuid.uuid4()
        self.collection.insert_one.return_value.inserted_id = fake_inserted_id

        log_data = log_ia_interaction(
            user_id=self.user_id,
            ebook_id=self.ebook_id,
            provider='openrouter',
            model='google/gemma-4-31b-it:free',
            prompt='Escribe un capítulo introductorio',
            tokens_used=240,
        )

        self.assertEqual(log_data['_id'], str(fake_inserted_id))
        self.collection.insert_one.assert_called_once()
        doc = self.collection.insert_one.call_args[0][0]
        self.assertEqual(doc['tokens_used'], 240)

    def test_log_ia_interaction_no_rompe_si_mongo_falla(self):
        self.collection.insert_one.side_effect = PyMongoError('Mongo caído')

        log_data = log_ia_interaction(
            user_id=self.user_id,
            ebook_id=self.ebook_id,
            provider='openrouter',
            model='google/gemma-4-31b-it:free',
            prompt='Prompt de contingencia',
            tokens_used=100,
        )
        self.assertEqual(log_data['tokens_used'], 100)


class AIGenerateEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='escritor@test.com',
            password='Clave-Segura-123',
            first_name='Carlos',
            last_name='Autor',
        )
        self.ebook = EbookMetadata.objects.create(
            author=self.user,
            title='Libro de Prueba',
        )
        self.ch_id = str(uuid.uuid4())
        self.sec_id = str(uuid.uuid4())

        self.url = '/api/ai/generate/'
        self.client.force_authenticate(user=self.user)

    @patch('apps.ai_engine.views.update_content')
    @patch('apps.ai_engine.views.log_ia_interaction')
    @patch('apps.ai_engine.views.AIClient')
    def test_generacion_exitosa_descuenta_saldo(self, mock_ai_class, mock_log, mock_update):
        mock_instance = MagicMock()
        mock_instance.generate_content.return_value = {
            'html': '<p>Texto generado por IA</p>',
            'tokens_used': 150,
            'provider': 'openrouter',
            'model': 'google/gemma-4-31b-it:free',
        }
        mock_ai_class.return_value = mock_instance

        payload = {
            'ebook_id': str(self.ebook.id),
            'chapter_id': self.ch_id,
            'section_id': self.sec_id,
            'prompt': 'Explica la fotosíntesis en detalle',
        }

        response = self.client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['credits_debited'], 10)
        self.assertEqual(response.data['credits_available'], 90)
        self.assertIn('Texto generado por IA', response.data['generated_html'])

        balance = CreditBalance.objects.get(usuario=self.user)
        self.assertEqual(balance.credits_available, 90)

    def test_generacion_falla_si_saldo_es_insuficiente(self):
        balance = CreditBalance.objects.get(usuario=self.user)
        balance.credits_available = 5  # Menor a 10
        balance.save()

        payload = {
            'ebook_id': str(self.ebook.id),
            'chapter_id': self.ch_id,
            'section_id': self.sec_id,
            'prompt': 'Quiero generar contenido sin saldo',
        }

        response = self.client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.data['error']['code'], 'INSUFFICIENT_CREDITS')
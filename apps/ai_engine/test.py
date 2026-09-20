import uuid
from unittest.mock import MagicMock, patch
from django.test import TestCase
from pymongo.errors import PyMongoError

from .services import log_ia_interaction


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
        doc_guardado = self.collection.insert_one.call_args[0][0]
        self.assertEqual(doc_guardado['tokens_used'], 240)
        self.assertEqual(doc_guardado['model'], 'google/gemma-4-31b-it:free')

    def test_log_ia_interaction_no_rompe_si_mongo_falla(self):
        self.collection.insert_one.side_effect = PyMongoError('Mongo no responde')

        log_data = log_ia_interaction(
            user_id=self.user_id,
            ebook_id=self.ebook_id,
            provider='openrouter',
            model='google/gemma-4-31b-it:free',
            prompt='Prompt de contingencia',
            tokens_used=100,
        )

        # Retorna el diccionario sin lanzar excepción no controlada
        self.assertEqual(log_data['tokens_used'], 100)
        self.assertNotIn('_id', log_data)
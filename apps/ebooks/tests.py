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
        # Simular MongoDB sin establecer una conexión real.
        patcher = patch('apps.ebooks.services.get_mongo_db')
        mock_get_db = patcher.start()
        self.addCleanup(patcher.stop)

        self.collection = MagicMock()
        mock_get_db.return_value.__getitem__.return_value = (
            self.collection
        )

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

    @patch('apps.ebooks.services._emit_progress')
    @patch('apps.ebooks.services.threading.Thread')
    @patch('apps.ebooks.services.AIClient')
    @patch('apps.ebooks.services.log_ia_interaction')
    def test_crear_ebook_genera_contenido_y_debita_creditos(
        self,
        mock_log,
        mock_ai,
        mock_thread,
        mock_emit_progress,
    ):
        mock_ai_instance = MagicMock()
        mock_ai_instance.generate_content.return_value = {
            'html': json.dumps([
                {
                    'title': 'Cap 1',
                    'sections': [
                        {
                            'title': 'Sec 1',
                            'html': '<p>Contenido</p>',
                        },
                    ],
                },
            ]),
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

        response = self.client.post(
            self.url,
            payload,
            format='json',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        ebook = EbookMetadata.objects.get()
        self.assertEqual(ebook.author, self.user)
        self.assertEqual(ebook.title, 'Mi libro con IA')
        self.assertEqual(
            response.data['ebook_id'],
            str(ebook.id),
        )
        self.assertEqual(
            response.data['status'],
            'PROCESSING',
        )

        # El hilo está simulado: la generación todavía no se ejecutó.
        mock_thread.assert_called_once()

        # Ejecutar manualmente la tarea asíncrona.
        thread_kwargs = mock_thread.call_args.kwargs
        thread_kwargs['target'](*thread_kwargs['args'])

        ebook.refresh_from_db()
        self.assertEqual(ebook.status, 'COMPLETED')

        # Saldo inicial 1000 menos 100 créditos de generación.
        balance = CreditBalance.objects.get(usuario=self.user)
        self.assertEqual(balance.credits_available, 900)

        self.collection.insert_one.assert_called_once()
        doc = self.collection.insert_one.call_args[0][0]

        self.assertEqual(doc['_id'], str(ebook.id))
        self.assertEqual(doc['ebook_id'], str(ebook.id))
        self.assertEqual(len(doc['chapters']), 1)
        self.assertEqual(
            doc['chapters'][0]['title'],
            'Cap 1',
        )
        self.assertEqual(
            doc['chapters'][0]['sections'][0]['html'],
            '<p>Contenido</p>',
        )

        mock_ai_instance.generate_content.assert_called_once()
        mock_log.assert_called_once()

    def test_crear_ebook_sin_saldo_retorna_402(self):
        balance = CreditBalance.objects.get(
            usuario=self.user,
        )
        balance.credits_available = 20
        balance.save()

        response = self.client.post(
            self.url,
            {'title': 'Libro Rechazado'},
            format='json',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_402_PAYMENT_REQUIRED,
        )
        self.assertEqual(EbookMetadata.objects.count(), 0)

        balance.refresh_from_db()
        self.assertEqual(balance.credits_available, 20)

    @patch('apps.ebooks.services._emit_progress')
    @patch('apps.ebooks.services.threading.Thread')
    @patch('apps.ebooks.services.AIClient')
    @patch('apps.ebooks.services.log_ia_interaction')
    def test_crear_ebook_marca_failed_si_mongo_falla(
        self,
        mock_log,
        mock_ai,
        mock_thread,
        mock_emit_progress,
    ):
        mock_ai_instance = MagicMock()
        mock_ai_instance.generate_content.return_value = {
            'html': json.dumps([
                {
                    'title': 'Cap 1',
                    'sections': [
                        {
                            'title': 'Sec 1',
                            'html': '<p>Contenido</p>',
                        },
                    ],
                },
            ]),
            'tokens_used': 100,
            'provider': 'openrouter',
            'model': 'test-model',
        }
        mock_ai.return_value = mock_ai_instance

        self.collection.insert_one.side_effect = PyMongoError(
            'Mongo caído',
        )

        response = self.client.post(
            self.url,
            {'title': 'Mi libro'},
            format='json',
        )

        # La API acepta la petición antes de ejecutar el trabajo.
        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(EbookMetadata.objects.count(), 1)

        ebook = EbookMetadata.objects.get()
        self.assertEqual(ebook.status, 'PROCESSING')

        # Ejecutar el trabajo manualmente para comprobar el fallo.
        thread_kwargs = mock_thread.call_args.kwargs
        thread_kwargs['target'](*thread_kwargs['args'])

        ebook.refresh_from_db()
        self.assertEqual(ebook.status, 'FAILED')

        self.collection.insert_one.assert_called_once()
        mock_log.assert_not_called()

        # El descuento se revirtió después del fallo de persistencia.
        balance = CreditBalance.objects.get(
            usuario=self.user,
        )
        self.assertEqual(balance.credits_available, 1000)

    def test_listar_devuelve_solo_libros_propios_paginados(self):
        EbookMetadata.objects.create(
            author=self.user,
            title='Propio',
        )
        EbookMetadata.objects.create(
            author=self.other,
            title='Ajeno',
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(
            [
                ebook['title']
                for ebook in response.data['results']
            ],
            ['Propio'],
        )

    def test_busqueda_avanzada_filtra_por_titulo_y_descripcion(self):
        EbookMetadata.objects.create(
            author=self.user,
            title='Cocina Rápida',
            description='Recetas',
        )
        EbookMetadata.objects.create(
            author=self.user,
            title='Guía Fitness',
            description='Entrenamiento y cocina',
        )
        EbookMetadata.objects.create(
            author=self.user,
            title='Programación en Python',
            description='Backend',
        )

        response = self.client.get(
            f'{self.url}?search=cocina',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(response.data['count'], 2)

        titulos = [
            ebook['title']
            for ebook in response.data['results']
        ]

        self.assertIn('Cocina Rápida', titulos)
        self.assertIn('Guía Fitness', titulos)
        self.assertNotIn('Programación en Python', titulos)

    def test_detalle_de_libro_ajeno_devuelve_404(self):
        ajeno = EbookMetadata.objects.create(
            author=self.other,
            title='Ajeno',
        )

        response = self.client.get(
            f'{self.url}{ajeno.id}/',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_eliminar_borra_en_postgres_y_mongo(self):
        ebook = EbookMetadata.objects.create(
            author=self.user,
            title='Propio',
        )
        ebook_id = str(ebook.id)

        response = self.client.delete(
            f'{self.url}{ebook_id}/',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )
        self.assertEqual(EbookMetadata.objects.count(), 0)
        self.collection.delete_one.assert_called_once_with(
            {'_id': ebook_id},
        )

    def test_eliminar_con_mongo_caido_igual_borra_el_libro(self):
        ebook = EbookMetadata.objects.create(
            author=self.user,
            title='Propio',
        )

        self.collection.delete_one.side_effect = PyMongoError(
            'Mongo caído',
        )

        response = self.client.delete(
            f'{self.url}{ebook.id}/',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )
        self.assertEqual(EbookMetadata.objects.count(), 0)

    def test_requiere_autenticacion(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
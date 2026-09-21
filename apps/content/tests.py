import copy
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from pymongo.errors import PyMongoError
from rest_framework import status
from rest_framework.test import APITestCase

from apps.ebooks.models import EbookMetadata

User = get_user_model()


class FakeCollection:
    """Colección de Mongo en memoria: imita find_one/update_one con filtro por versión."""

    def __init__(self, doc):
        self.doc = doc

    def find_one(self, filtro):
        if self.doc['_id'] != filtro['_id']:
            return None
        return copy.deepcopy(self.doc)

    def update_one(self, filtro, update):
        if self.doc['_id'] != filtro['_id'] or self.doc.get('version') != filtro['version']:
            return SimpleNamespace(matched_count=0)
        self.doc.update(update['$set'])
        self.doc['version'] = (self.doc.get('version') or 0) + update['$inc']['version']
        return SimpleNamespace(matched_count=1)


class EbookContentApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='autor@test.com', password='Clave-Segura-123',
            first_name='Ana', last_name='Autora',
        )
        self.other = User.objects.create_user(
            email='otro@test.com', password='Clave-Segura-123',
            first_name='Otto', last_name='Otro',
        )
        self.ebook = EbookMetadata.objects.create(author=self.user, title='Mi libro')

        self.ch1, self.ch2 = str(uuid.uuid4()), str(uuid.uuid4())
        self.s1, self.s2, self.s3 = (str(uuid.uuid4()) for _ in range(3))

        # Mismo formato que el documento base de tk049, ya con capítulos cargados.
        self.collection = FakeCollection({
            '_id': str(self.ebook.id),
            'chapters': [
                {'id': self.ch1, 'title': 'Capítulo 1', 'sections': [
                    {'id': self.s1, 'title': 'Intro', 'html': '<p>Hola</p>'},
                    {'id': self.s2, 'title': 'Desarrollo', 'html': ''},
                ]},
                {'id': self.ch2, 'title': 'Capítulo 2', 'sections': [
                    {'id': self.s3, 'title': 'Cierre', 'html': ''},
                ]},
            ],
            'created_at': datetime(2026, 1, 1),
            'updated_at': datetime(2026, 1, 1),
        })

        patcher = patch('apps.content.services.get_mongo_db')
        mock_get_db = patcher.start()
        self.addCleanup(patcher.stop)
        mock_get_db.return_value.__getitem__.return_value = self.collection

        self.url = f'/api/ebooks/{self.ebook.id}/content/'
        self.client.force_authenticate(user=self.user)

    def chapter_ids(self):
        return [chapter['id'] for chapter in self.collection.doc['chapters']]

    def simular_escritor_concurrente(self, veces):
        """Hace que los primeros 'veces' guardados pierdan la carrera contra otro escritor."""
        original = self.collection.update_one
        llamadas = []

        def update_con_carrera(filtro, update):
            llamadas.append(1)
            if len(llamadas) <= veces:
                self.collection.doc['version'] = (self.collection.doc.get('version') or 0) + 1
            return original(filtro, update)

        self.collection.update_one = update_con_carrera
        return llamadas

    # ---------- GET ----------

    def test_get_devuelve_el_arbol_completo(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['ebook_id'], str(self.ebook.id))
        self.assertEqual([c['id'] for c in response.data['chapters']], [self.ch1, self.ch2])
        self.assertEqual(response.data['chapters'][0]['sections'][0]['html'], '<p>Hola</p>')

    def test_get_de_libro_ajeno_devuelve_404(self):
        self.client.force_authenticate(user=self.other)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_requiere_autenticacion(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_devuelve_503_si_mongo_falla(self):
        self.collection.find_one = MagicMock(side_effect=PyMongoError('Mongo caido'))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    # ---------- PATCH ----------

    def test_patch_actualiza_html_y_lo_sanitiza(self):
        payload = {'sections': [{
            'chapter_id': self.ch1, 'section_id': self.s2,
            'html': '<p>Nuevo</p><script>alert(1)</script>',
        }]}

        response = self.client.patch(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.collection.doc['chapters'][0]['sections'][1]['html'], '<p>Nuevo</p>')

    def test_patch_reordena_capitulos(self):
        response = self.client.patch(
            self.url, {'chapters_order': [self.ch2, self.ch1]}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.chapter_ids(), [self.ch2, self.ch1])

    def test_patch_html_y_orden_se_guardan_en_una_sola_escritura(self):
        payload = {
            'sections': [{'chapter_id': self.ch2, 'section_id': self.s3, 'html': '<p>Fin</p>'}],
            'chapters_order': [self.ch2, self.ch1],
        }

        response = self.client.patch(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.collection.doc['version'], 1)  # una sola escritura
        self.assertEqual(self.chapter_ids(), [self.ch2, self.ch1])
        self.assertEqual(self.collection.doc['chapters'][0]['sections'][0]['html'], '<p>Fin</p>')

    def test_patch_con_orden_incompleto_devuelve_400_y_no_cambia_nada(self):
        response = self.client.patch(self.url, {'chapters_order': [self.ch1]}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.chapter_ids(), [self.ch1, self.ch2])
        self.assertNotIn('version', self.collection.doc)

    def test_patch_con_seccion_inexistente_no_aplica_ningun_cambio(self):
        payload = {
            'chapters_order': [self.ch2, self.ch1],  # válido...
            'sections': [{'chapter_id': self.ch1, 'section_id': str(uuid.uuid4()), 'html': '<p>x</p>'}],  # ...pero esto no
        }

        response = self.client.patch(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.chapter_ids(), [self.ch1, self.ch2])  # el reorden tampoco se aplicó

    def test_patch_vacio_devuelve_400(self):
        response = self.client.patch(self.url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_de_libro_ajeno_devuelve_404_y_no_cambia_nada(self):
        self.client.force_authenticate(user=self.other)

        response = self.client.patch(
            self.url, {'chapters_order': [self.ch2, self.ch1]}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.chapter_ids(), [self.ch1, self.ch2])

    # ---------- Concurrencia ----------

    def test_reintenta_si_otro_guardado_gana_la_carrera(self):
        llamadas = self.simular_escritor_concurrente(veces=1)

        response = self.client.patch(
            self.url, {'chapters_order': [self.ch2, self.ch1]}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(llamadas), 2)  # el primer intento perdió, el segundo entró
        self.assertEqual(self.chapter_ids(), [self.ch2, self.ch1])

    def test_devuelve_409_si_el_conflicto_persiste(self):
        llamadas = self.simular_escritor_concurrente(veces=99)

        response = self.client.patch(
            self.url, {'chapters_order': [self.ch2, self.ch1]}, format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(len(llamadas), 3)  # MAX_SAVE_ATTEMPTS
        self.assertEqual(self.chapter_ids(), [self.ch1, self.ch2])
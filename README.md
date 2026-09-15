# Pinta Ebook - Backend API

API REST para **Pinta Ebook**, una plataforma web diseñada para la creación, maquetación y gestión de ebooks asistidos por Inteligencia Artificial generativa.

Este servicio backend gestiona la persistencia transaccional, el control de acceso basado en roles y el flujo de autenticación unificada (local y federada con Google).

---

## 🛠️ Stack Tecnológico

* **Lenguaje:** Python 3.12+
* **Framework:** Django & Django REST Framework (DRF)
* **Autenticación:** `djangorestframework-simplejwt` (JWT) & `google-auth` (OAuth 2.0 / OpenID Connect)
* **Base de Datos:** PostgreSQL
* **Gestión de Entorno:** `django-environ`

---

## Levantar back-end:

**1**. Usar las variables en .env correspondientes declaradas en la documentacion.
**2**. Teniendo ya sea Docker Desktop: docker compose up -d --build | Teniendo Docker WSL2 por ubuntu: sudo docker compose up -d --build
**3**. Aplicar los esquemas a la base de datos dentro del contenedor:
docker compose exec web python manage.py migrate

## 🏛️ Arquitectura del Proyecto

El backend sigue un diseño modular por capas desacopladas dentro del directorio `apps/`:

```text
pintaebook_backend/
├── apps/
│   ├── accounts/          # Gestión de usuarios, roles y autenticación
│   │   ├── migrations/    # Esquemas y seeds de datos
│   │   ├── models.py      # Custom User y Role
│   │   ├── serializers.py # Validación y tipado de datos de entrada
│   │   ├── services.py    # Lógica de negocio, criptografía y tokens
│   │   ├── urls.py        # Enrutamiento de endpoints
│   │   └── views.py       # Controladores HTTP (APIView)
│   ├── ebooks/            # Gestión de proyectos y libros (en desarrollo)
│   ├── ai_engine/         # Integración con modelos generativos (en desarrollo)
│   └── billing/           # Sistema de créditos y suscripciones (en desarrollo)
├── config/                # Configuraciones base, local y producción
└── requirements.txt       # Dependencias del proyecto 

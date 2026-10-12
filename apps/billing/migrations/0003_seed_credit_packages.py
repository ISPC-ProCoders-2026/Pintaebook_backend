from decimal import Decimal

from django.db import migrations

# Catálogo inicial de paquetes. Los precios están en pesos argentinos (ARS).
INITIAL_PACKAGES = [
    {'nombre': 'Básico', 'cantidad_creditos': 100, 'precio': Decimal('1000.00')},
    {'nombre': 'Estándar', 'cantidad_creditos': 500, 'precio': Decimal('4000.00')},
    {'nombre': 'Pro', 'cantidad_creditos': 1000, 'precio': Decimal('7000.00')},
]


def create_initial_packages(apps, schema_editor):
    CreditPackage = apps.get_model('billing', 'CreditPackage')
    for package in INITIAL_PACKAGES:
        # get_or_create por nombre (UNIQUE): si ya existe no se pisa su precio.
        CreditPackage.objects.get_or_create(
            nombre=package['nombre'],
            defaults={
                'cantidad_creditos': package['cantidad_creditos'],
                'precio': package['precio'],
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_creditpackage_paymenttransaction'),
    ]

    operations = [
        # Sin reverse: borrar paquetes puede fallar (PROTECT) si ya tienen ventas.
        migrations.RunPython(create_initial_packages, reverse_code=migrations.RunPython.noop),
    ]

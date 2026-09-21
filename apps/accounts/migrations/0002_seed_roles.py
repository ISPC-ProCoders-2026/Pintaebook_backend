from django.db import migrations

def create_initial_roles(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    roles = ['ADMIN', 'AUTOR']
    for role_name in roles:
        Role.objects.get_or_create(nombre_rol=role_name)

def remove_initial_roles(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    Role.objects.filter(nombre_rol__in=['ADMIN', 'AUTOR']).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_initial_roles, reverse_code=remove_initial_roles),
    ]
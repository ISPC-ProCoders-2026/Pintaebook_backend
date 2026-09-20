import uuid
from django.conf import settings
from django.db import models

class CreditBalance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='credit_balance',
        db_column='usuario_id',
    )
    credits_available = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'balances_credito'

    def __str__(self):
        return f"{self.usuario.email} - {self.credits_available} créditos"
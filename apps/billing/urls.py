from django.urls import path
from .views import BillingBalanceView

urlpatterns = [
    path('billing/balance/', BillingBalanceView.as_view(), name='billing-balance'),
]
from django.urls import path
from .views import (
    BillingBalanceView,
    BillingCheckoutView,
    BillingWebhookView,
    CreditPackageListView,
)

urlpatterns = [
    path('billing/balance/', BillingBalanceView.as_view(), name='billing-balance'),
    path('billing/packages/', CreditPackageListView.as_view(), name='billing-packages'),
    path('billing/checkout/', BillingCheckoutView.as_view(), name='billing-checkout'),
    path('billing/webhook/', BillingWebhookView.as_view(), name='billing-webhook'),
]
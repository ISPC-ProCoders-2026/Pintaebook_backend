from django.urls import path
from .views import BillingBalanceView, BillingCheckoutView, BillingWebhookView

urlpatterns = [
    path('billing/balance/', BillingBalanceView.as_view(), name='billing-balance'),
    path('billing/checkout/', BillingCheckoutView.as_view(), name='billing-checkout'),
    path('billing/webhook/', BillingWebhookView.as_view(), name='billing-webhook'),
]
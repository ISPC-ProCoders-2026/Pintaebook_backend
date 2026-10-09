from django.urls import path
from .views import BillingBalanceView, BillingCheckoutView

urlpatterns = [
    path('billing/balance/', BillingBalanceView.as_view(), name='billing-balance'),
    path('billing/checkout/', BillingCheckoutView.as_view(), name='billing-checkout'),
]
# pretixkonnect/urls.py

from django.urls import path
from . import views

app_name = 'pretixkonnect'

urlpatterns = [
    path('settings/', views.konnect_settings_view, name='konnect_settings'),
    path('api/payment/konnect/notification/', views.konnect_webhook, name='konnect_webhook'),
]

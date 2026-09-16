from django.urls import path

from . import views

urlpatterns = [
    path("", views.collection, name="cloud-account-list"),
    path("<uuid:account_id>/", views.detail, name="cloud-account-detail"),
    path("<uuid:account_id>/validate/", views.validate, name="cloud-account-validate"),
    path("<uuid:account_id>/rotate-credentials/", views.rotate, name="cloud-account-rotate"),
    path(
        "<uuid:account_id>/capabilities/", views.capability_list, name="cloud-account-capabilities"
    ),
]

from django.urls import path

from . import views

urlpatterns = [
    path("", views.collection, name="operation-list"),
    path("previews/", views.preview, name="operation-preview"),
    path("<uuid:operation_id>/", views.detail, name="operation-detail"),
    path("<uuid:operation_id>/cancel/", views.cancel, name="operation-cancel"),
    path("<uuid:operation_id>/retry/", views.retry, name="operation-retry"),
]

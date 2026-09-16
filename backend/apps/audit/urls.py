from django.urls import path

from .views import collection

urlpatterns = [path("", collection, name="audit-event-list")]

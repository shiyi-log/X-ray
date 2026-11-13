from django.urls import path

from .upgrade import upgrade

urlpatterns = [path("", upgrade, name="system-upgrade")]

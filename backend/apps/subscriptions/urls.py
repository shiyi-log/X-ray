from django.urls import path

from .public_views import public_subscription

urlpatterns = [path("s/<str:raw_token>", public_subscription, name="public-subscription")]

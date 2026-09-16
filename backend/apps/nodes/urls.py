from django.urls import path

from . import views

pool_urlpatterns = [
    path("", views.pool_collection, name="node-pool-list"),
    path("<uuid:pool_id>/", views.pool_detail, name="node-pool-detail"),
]

node_urlpatterns = [
    path("", views.node_collection, name="node-list"),
    path("<uuid:node_id>/", views.node_detail, name="node-detail"),
    path("<uuid:node_id>/actions/<str:action>/", views.node_action, name="node-action"),
]

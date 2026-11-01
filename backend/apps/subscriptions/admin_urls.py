from django.urls import path

from . import admin_views, management_api

profile_urlpatterns = [
    path("", admin_views.profile_collection, name="access-profile-list"),
    path("<uuid:profile_id>/", admin_views.profile_detail, name="access-profile-detail"),
    path("<uuid:profile_id>/subscription/", admin_views.issue, name="subscription-issue"),
    path(
        "<uuid:profile_id>/force-revoke/",
        admin_views.force_revoke,
        name="subscription-force-revoke",
    ),
]

subscription_urlpatterns = [
    path("", admin_views.subscription_collection, name="subscription-list"),
    path("plans/", management_api.plans, name="subscription-plans"),
    path("plans/<uuid:plan_id>/", management_api.plans, name="subscription-plan-detail"),
    path("catalog/", management_api.catalog, name="subscription-catalog"),
    path("<uuid:subscription_id>/", management_api.subscription_detail, name="subscription-detail"),
    path(
        "<uuid:subscription_id>/tokens/",
        admin_views.token_collection,
        name="subscription-token-list",
    ),
    path(
        "<uuid:subscription_id>/tokens/<uuid:token_id>/revoke/",
        admin_views.revoke_token,
        name="subscription-token-revoke",
    ),
    path("<uuid:subscription_id>/assign/", management_api.assign, name="subscription-assign"),
    path("<uuid:subscription_id>/rotate/", admin_views.rotate, name="subscription-rotate"),
    path("<uuid:subscription_id>/publish/", admin_views.publish, name="subscription-publish"),
]

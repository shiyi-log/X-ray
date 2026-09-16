from django.urls import path

from . import views

urlpatterns = [
    path("csrf", views.csrf, name="auth-csrf"),
    path("login", views.login, name="auth-login"),
    path("totp/setup", views.totp_setup, name="auth-totp-setup"),
    path("totp/confirm", views.totp_confirm, name="auth-totp-confirm"),
    path("totp/verify", views.totp_verify, name="auth-totp-verify"),
    path("recovery-code", views.recovery_code, name="auth-recovery-code"),
    path("session", views.session, name="auth-session"),
    path("logout", views.logout, name="auth-logout"),
    path("logout-all", views.logout_all, name="auth-logout-all"),
    path("step-up", views.step_up, name="auth-step-up"),
    path("change-password", views.change_password, name="auth-change-password"),
]

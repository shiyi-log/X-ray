from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    action = models.CharField(max_length=120)
    target_type = models.CharField(max_length=120)
    target_id = models.CharField(max_length=120, blank=True, default="")
    result = models.CharField(max_length=40)
    metadata = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    request_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

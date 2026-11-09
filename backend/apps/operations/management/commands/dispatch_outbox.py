from django.core.management.base import BaseCommand

from apps.operations.outbox import dispatch_pending
from apps.operations.tasks import execute_operation
from config.celery import app as celery_app


class Command(BaseCommand):
    help = "Dispatch durable Operation outbox entries to Celery."

    def handle(self, *args, **options):
        count = dispatch_pending(
            lambda operation_id, schema_version: celery_app.send_task(
                execute_operation.name,
                args=(operation_id, schema_version),
            )
        )
        self.stdout.write(f"dispatched={count}")

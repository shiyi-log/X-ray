from apps.subscriptions.tasks import refresh_usage_and_limits
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Collect trusted node usage and enqueue expired/quota access removal."

    def handle(self, *args, **options):
        self.stdout.write(str(refresh_usage_and_limits()))

import json

from apps.subscriptions.runtime import subscription_runtime
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Read-only subscription deployment checks without SSH or queue dispatch."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true")

    def handle(self, *args, **options):
        result = subscription_runtime()
        self.stdout.write(json.dumps(result, sort_keys=True))
        if options["strict"] and result["status"] != "ready":
            raise CommandError("SUBSCRIPTION_RUNTIME_INCOMPLETE")

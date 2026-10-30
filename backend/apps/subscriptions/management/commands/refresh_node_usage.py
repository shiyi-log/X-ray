from django.core.management.base import BaseCommand, CommandError

from common.errors import DomainError

from apps.subscriptions.metering import collect_node_once


class Command(BaseCommand):
    help = "Collect usage for one ready node selected by UUID; does not enforce global limits."

    def add_arguments(self, parser):
        parser.add_argument("--node-id", required=True)

    def handle(self, *args, **options):
        node_id = options["node_id"]
        try:
            collected = collect_node_once(node_id)
        except DomainError as exc:
            raise CommandError(exc.code) from None
        except Exception:
            raise CommandError("USAGE_COLLECTION_FAILED") from None
        self.stdout.write(f"node={node_id} profiles_collected={collected}")

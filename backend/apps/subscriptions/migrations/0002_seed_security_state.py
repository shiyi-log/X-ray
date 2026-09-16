from django.db import migrations


def seed_open_security_state(apps, schema_editor):
    SecurityState = apps.get_model("subscriptions", "SecurityState")
    SecurityState.objects.get_or_create(singleton_key=1, defaults={"mode": "OPEN"})


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0001_initial")]

    operations = [migrations.RunPython(seed_open_security_state, migrations.RunPython.noop)]

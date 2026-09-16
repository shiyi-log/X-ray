from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [
        migrations.CreateModel(
            name="SuperAdmin",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=True, help_text="Designates that this user has all permissions without explicitly assigning them.", verbose_name="superuser status")),
                ("username", models.CharField(max_length=150, unique=True)),
                ("singleton_key", models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("is_staff", models.BooleanField(default=True)),
                ("session_version", models.PositiveBigIntegerField(default=1)),
                ("totp_secret_envelope", models.JSONField(blank=True, null=True)),
                ("last_totp_step", models.BigIntegerField(default=-1)),
                ("recovery_code_hashes", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("groups", models.ManyToManyField(blank=True, help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.", related_name="superadmin_set", related_query_name="superadmin", to="auth.group", verbose_name="groups")),
                ("user_permissions", models.ManyToManyField(blank=True, help_text="Specific permissions for this user.", related_name="superadmin_set", related_query_name="superadmin", to="auth.permission", verbose_name="user permissions")),
            ],
            options={"constraints": [models.CheckConstraint(condition=models.Q(("singleton_key", 1)), name="only_admin_slot_one")]},
        ),
        migrations.CreateModel(
            name="AdminSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key_hash", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("expires_at", models.DateTimeField()),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("session_version", models.PositiveBigIntegerField()),
                ("admin", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="sessions", to="identity.superadmin")),
            ],
        ),
    ]

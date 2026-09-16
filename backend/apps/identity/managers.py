from django.contrib.auth.base_user import BaseUserManager


class SuperAdminManager(BaseUserManager):
    use_in_migrations = True

    def create_superuser(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("username is required")
        if not password:
            raise ValueError("password is required")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        # singleton_key is deliberately not caller controlled.
        extra_fields["singleton_key"] = 1
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

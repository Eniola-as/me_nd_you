from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def normalize_email(self, email):
        # Emails are compared case-insensitively, so store them lowercased.
        return super().normalize_email((email or "").strip()).lower()

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not (extra_fields["is_staff"] and extra_fields["is_superuser"]):
            raise ValueError("Superusers must have is_staff and is_superuser set.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """A person using Me & You. Signs in with email and password; there is
    no username. Profile fields and couple membership come later."""

    username = None
    email = models.EmailField("email address", unique=True)
    # What a partner sees. The email is private to its owner (and admins).
    display_name = models.CharField(max_length=40, blank=True, default="")
    # Set the first time a verification link is used. Verification is a
    # reminder only: unverified users can use everything.
    email_verified_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        constraints = [
            # unique=True alone is case-sensitive on PostgreSQL.
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    @property
    def name_for_partner(self):
        """Never falls back to the email address."""
        return self.display_name or "Your partner"

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)


class Consent(models.Model):
    """One agreement a user gave, with when and to which policy version.
    Rows are only added: withdrawing consent means deleting the account."""

    AGE = "age_18"
    TERMS = "terms_privacy"
    SENSITIVE = "sensitive_data"
    TRANSFER = "data_transfer"
    KIND_CHOICES = [
        (AGE, "Confirmed being 18 or older"),
        (TERMS, "Agreed to the Terms of Use and Privacy Policy"),
        (SENSITIVE, "Consented to intimate and sensitive content being stored and processed"),
        (TRANSFER, "Consented to data being stored and processed outside Nigeria"),
    ]

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="consents")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    policy_version = models.CharField(max_length=40)
    given_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["given_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["user", "kind", "policy_version"], name="accounts_consent_once_per_version"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} ({self.policy_version})"

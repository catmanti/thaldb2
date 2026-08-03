from typing import ClassVar

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import CustomUserManager


class User(AbstractUser):
    class Role(models.TextChoices):
        DOCTOR = "DOCTOR", "Doctor"
        NURSE = "NURSE", "Nurse"
        DATA_ENTRY = "DATA_ENTRY", "Data Entry Clerk"
        UNIT_ADMIN = "UNIT_ADMIN", "Unit Administrator"
        SYSTEM_ADMIN = "SYSTEM_ADMIN", "System Administrator"

    COLOR_SCHEME_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ("blue", "Default Blue"),
        ("emerald", "Emerald Green"),
        ("purple", "Royal Purple"),
        ("slate", "Slate Grey"),
        ("dark", "Dark Mode"),
    ]

    username = None  # Remove username field
    email = models.EmailField("email address", unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    # --- Role & Permissions ---
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DATA_ENTRY)
    primary_unit = models.ForeignKey(
        "clients.ThalassemiaUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_members",
    )

    # --- Preferences & UI Settings ---
    dark_mode = models.BooleanField(default=False)
    color_scheme = models.CharField(max_length=20, choices=COLOR_SCHEME_CHOICES, default="blue")
    preferences = models.JSONField(default=dict, blank=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    def __str__(self):
        full_name = self.get_full_name().strip()
        return f"{full_name} ({self.email})" if full_name else self.email

    @property
    def is_doctor(self):
        return self.role == self.Role.DOCTOR

    @property
    def is_unit_admin(self):
        return self.role in (self.Role.UNIT_ADMIN, self.Role.SYSTEM_ADMIN)

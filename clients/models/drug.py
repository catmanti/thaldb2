from django.db import models
from .client import Client


class DrugName(models.Model):
    """
    Drug names.
    """

    name = models.CharField(max_length=100, unique=True)
    dose = models.CharField(max_length=50, blank=True, null=True)
    regimen = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True) # inactive drugs will not be shown in the drug dropdown.

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class Drug(models.Model):
    """DRUGS"""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="drugs")
    date_prescribed = models.DateField()
    drug_name = models.ForeignKey(DrugName, on_delete=models.SET_NULL, null=True)
    dose = models.CharField(max_length=50)
    regimen = models.CharField(max_length=100)
    duration = models.CharField(max_length=50)
    indication = models.CharField(max_length=200, blank=True, null=True)
    prescribed_by = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.drug_name} - {self.client.full_name}"

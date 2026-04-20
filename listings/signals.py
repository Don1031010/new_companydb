from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="listings.CompanyShareInfo")
def sync_shares_outstanding(sender, instance, **kwargs):
    """Keep Company.shares_outstanding in sync with the latest CompanyShareInfo row."""
    from listings.models import Company, CompanyShareInfo

    latest = (
        CompanyShareInfo.objects
        .filter(company_id=instance.company_id)
        .order_by("-as_of_date")
        .values_list("total_shares", flat=True)
        .first()
    )
    if latest is not None:
        Company.objects.filter(pk=instance.company_id).update(shares_outstanding=latest)

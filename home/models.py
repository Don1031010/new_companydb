from django.db import models
from wagtail.models import Page
from wagtail.fields import RichTextField
from wagtail.admin.panels import FieldPanel


class HomePage(Page):
    intro = RichTextField(blank=True, verbose_name="イントロ文")

    content_panels = Page.content_panels + [
        FieldPanel("intro"),
    ]

    def get_context(self, request, *args, **kwargs):
        from listings.models import Company, Listing, INDUSTRY_33_CHOICES

        context = super().get_context(request, *args, **kwargs)

        industry_lookup = dict(INDUSTRY_33_CHOICES)

        context["total_companies"] = Company.objects.count()
        context["active_companies"] = Company.objects.filter(status="active").count()

        context["segment_counts"] = {
            key: Listing.objects.filter(market_segment=key, status="active").count()
            for key in ("tse_prime", "tse_standard", "tse_growth")
        }

        raw_industry = (
            Company.objects.filter(status="active")
            .exclude(industry_33="")
            .values("industry_33")
            .annotate(count=models.Count("id"))
            .order_by("-count")[:10]
        )
        context["industry_stats"] = [
            {
                "name": industry_lookup.get(row["industry_33"], row["industry_33"]),
                "count": row["count"],
            }
            for row in raw_industry
        ]

        context["recent_companies"] = Company.objects.order_by("-updated_at")[:8]

        return context

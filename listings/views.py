from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.db.models import Q

from .models import Company, INDUSTRY_33_CHOICES, MARKET_SEGMENT_CHOICES


def company_list(request):
    q = request.GET.get("q", "").strip()
    industry = request.GET.get("industry", "")
    segment = request.GET.get("segment", "")

    companies = Company.objects.prefetch_related("listings__exchange").order_by("stock_code")

    if q:
        companies = companies.filter(
            Q(stock_code__icontains=q)
            | Q(name_ja__icontains=q)
            | Q(name_kana__icontains=q)
            | Q(name_en__icontains=q)
        )

    if industry:
        companies = companies.filter(industry_33=industry)

    if segment:
        companies = companies.filter(listings__market_segment=segment, listings__status="active")

    paginator = Paginator(companies, 50)
    page_num = request.GET.get("page", 1)
    try:
        page_obj = paginator.page(page_num)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)

    return render(request, "listings/company_list.html", {
        "page_obj": page_obj,
        "q": q,
        "industry": industry,
        "segment": segment,
        "industry_choices": INDUSTRY_33_CHOICES,
        "segment_choices": MARKET_SEGMENT_CHOICES,
        "total_count": paginator.count,
    })

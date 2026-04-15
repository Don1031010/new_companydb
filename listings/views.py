from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render, get_object_or_404
from django.db.models import Q, F

from .models import Company, INDUSTRY_33_CHOICES, MARKET_SEGMENT_CHOICES

DISCLOSURE_BATCH = 20


def company_list(request):
    q = request.GET.get("q", "").strip()
    industry = request.GET.get("industry", "")
    segment = request.GET.get("segment", "")
    sort = request.GET.get("sort", "")

    companies = Company.objects.prefetch_related("listings__exchange").exclude(
        listings__market_segment="tse_pro"
    )

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

    if sort == "market_cap_asc":
        companies = companies.order_by(F("market_cap").asc(nulls_last=True))
    elif sort == "market_cap_desc":
        companies = companies.order_by(F("market_cap").desc(nulls_last=True))
    else:
        companies = companies.order_by("stock_code")

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
        "sort": sort,
        "industry_choices": INDUSTRY_33_CHOICES,
        "segment_choices": MARKET_SEGMENT_CHOICES,
        "total_count": paginator.count,
    })


def company_detail(request, stock_code):
    company = get_object_or_404(
        Company.objects.prefetch_related(
            "listings__exchange",
            "share_records__shareholder",
        ),
        stock_code=stock_code,
    )
    disclosures = company.disclosures.order_by("-disclosed_date")[:DISCLOSURE_BATCH]
    total_disclosures = company.disclosures.count()
    return render(request, "listings/company_detail.html", {
        "company": company,
        "disclosures": disclosures,
        "total_disclosures": total_disclosures,
        "disclosure_batch": DISCLOSURE_BATCH,
    })


def company_disclosures(request, stock_code):
    company = get_object_or_404(Company, stock_code=stock_code)
    offset = int(request.GET.get("offset", DISCLOSURE_BATCH))
    disclosures = company.disclosures.order_by("-disclosed_date")[offset:offset + DISCLOSURE_BATCH]
    return render(request, "listings/_disclosures_rows.html", {
        "disclosures": disclosures,
    })

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render, get_object_or_404
from django.db import models
from django.db.models import Q, F

from financials.models import ForecastRecord, DividendForecast, BalanceSheet

from .models import Company, StockExchange, INDUSTRY_33_CHOICES, MARKET_SEGMENT_CHOICES

DISCLOSURE_BATCH = 20


def company_list(request):
    q = request.GET.get("q", "").strip()
    industry = request.GET.get("industry", "")
    segment = request.GET.get("segment", "")
    exchange = request.GET.get("exchange", "")
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

    if exchange:
        companies = companies.filter(listings__exchange__code=exchange, listings__status="active")

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

    # Label for active exchange filter
    exchange_label = ""
    if exchange:
        try:
            ex = StockExchange.objects.get(code=exchange)
            exchange_label = ex.short_name or ex.name_ja
        except StockExchange.DoesNotExist:
            pass

    return render(request, "listings/company_list.html", {
        "page_obj": page_obj,
        "q": q,
        "industry": industry,
        "segment": segment,
        "exchange": exchange,
        "exchange_label": exchange_label,
        "sort": sort,
        "industry_choices": INDUSTRY_33_CHOICES,
        "segment_choices": MARKET_SEGMENT_CHOICES,
        "total_count": paginator.count,
    })


def company_detail(request, stock_code):
    company = get_object_or_404(
        Company.objects.prefetch_related("listings__exchange"),
        stock_code=stock_code,
    )
    latest_snapshot = (
        company.share_records
        .select_related("edinet_doc")
        .order_by("-as_of_date")
        .first()
    )
    major_shareholders = list(
        latest_snapshot.entries.select_related("shareholder").order_by("rank")
        if latest_snapshot else []
    )
    treasury_pct = None
    if latest_snapshot and latest_snapshot.treasury_shares:
        denom = latest_snapshot.total_shares or company.shares_outstanding
        if denom:
            treasury_pct = round(latest_snapshot.treasury_shares / denom * 100, 1)

    # Data for client-side treasury toggle (only when both totals are known)
    shareholder_toggle_data = None
    if latest_snapshot and latest_snapshot.total_shares and latest_snapshot.treasury_shares:
        shareholder_toggle_data = {
            "totalShares": latest_snapshot.total_shares,
            "treasuryShares": latest_snapshot.treasury_shares,
            "shareholders": [
                {
                    "rank": s.rank,
                    "name": s.shareholder.name,
                    "shares": s.shares,
                    "pct": float(s.percentage) if s.percentage is not None else None,
                }
                for s in major_shareholders
            ],
        }

    disclosures = company.disclosures.order_by("-disclosed_date")[:DISCLOSURE_BATCH]
    total_disclosures = company.disclosures.count()

    # Financial data — last 5 annual reports, oldest→newest for charts
    annual_reports = list(
        company.financial_reports
        .filter(fiscal_quarter=4)
        .prefetch_related("income_statements", "balance_sheets", "cash_flow_statements")
        .order_by("-period_end")[:5]
    )
    annual_reports.reverse()

    def _v(val, divisor=1_000):
        """千円 → 百万円; None stays None."""
        return round(val / divisor) if val is not None else None

    def _pct(val):
        """Ratio → percentage float rounded to 1dp; None stays None."""
        return round(float(val) * 100, 1) if val is not None else None

    def _yoy(curr, prev):
        if curr is not None and prev is not None and prev != 0:
            return round((curr - prev) / abs(prev), 4)
        return None

    fin_rows = []
    for r in annual_reports:
        is_ = next(iter(r.income_statements.all()), None)
        bs_ = next(iter(r.balance_sheets.all()), None)
        cf_ = next(iter(r.cash_flow_statements.all()), None)

        revenue = _v(is_.revenue) if is_ else None
        op_profit = _v(is_.operating_profit) if is_ else None
        prev = fin_rows[-1] if fin_rows else None

        fin_rows.append({
            "label": r.period_end.strftime("%Y/%m") if r.period_end else str(r.fiscal_year),
            "fiscal_year": r.fiscal_year,
            "period_end": r.period_end.isoformat() if r.period_end else None,
            # P&L
            "revenue":          revenue,
            "gross_profit":     _v(is_.gross_profit)      if is_ else None,
            "operating_profit": op_profit,
            "ordinary_profit":  _v(is_.ordinary_profit)   if is_ else None,
            "net_income":       _v(is_.net_income)        if is_ else None,
            "eps":              float(is_.eps)            if is_ and is_.eps is not None else None,
            "roe":              _pct(is_.roe)             if is_ else None,
            "operating_margin": round(op_profit / revenue * 100, 1) if op_profit is not None and revenue else None,
            "revenue_yoy":      _yoy(revenue,   prev["revenue"])          if prev else None,
            "op_profit_yoy":    _yoy(op_profit, prev["operating_profit"]) if prev else None,
            # B/S
            "total_assets":     _v(bs_.total_assets)      if bs_ else None,
            "net_assets":       _v(bs_.net_assets)        if bs_ else None,
            "equity_ratio":     _pct(bs_.equity_ratio)    if bs_ else None,
            "bps":              float(bs_.book_value_per_share) if bs_ and bs_.book_value_per_share is not None else None,
            "interest_bearing_debt": _v(bs_.interest_bearing_debt) if bs_ else None,
            # CF
            "operating_cf":  _v(cf_.operating_cf)  if cf_ else None,
            "investing_cf":  _v(cf_.investing_cf)  if cf_ else None,
            "financing_cf":  _v(cf_.financing_cf)  if cf_ else None,
            "capex":         _v(cf_.capex)          if cf_ else None,
            "depreciation":  _v(cf_.depreciation)   if cf_ else None,
            "fcf":           _v(cf_.free_cash_flow)  if cf_ else None,
        })

    # Valuation metrics — use the most recent balance sheet across all report types
    _latest_bs = (
        BalanceSheet.objects
        .filter(report__company=company, book_value_per_share__isnull=False)
        .order_by("-report__period_end")
        .first()
    )
    _latest_bps = float(_latest_bs.book_value_per_share) if _latest_bs else None

    def _ratio(a, b, decimals=2):
        if a is not None and b and b != 0:
            return round(a / b, decimals)
        return None

    valuation = {
        "forecast_eps": None,
        "actual_bps": _latest_bps,
        "forecast_dividend": None,
        "per": None,
        "pbr": None,
        "dividend_yield": None,
    }

    # Latest full-year earnings forecast
    _fc = (
        company.forecast_records
        .filter(target_fiscal_quarter=4)
        .order_by("-announced_at")
        .first()
    )
    latest_forecast = None
    if _fc:
        latest_forecast = {
            "pk": _fc.pk,
            "fiscal_year": _fc.target_fiscal_year,
            "announced_at": _fc.announced_at,
            "revenue":          _v(_fc.revenue),
            "operating_profit": _v(_fc.operating_profit),
            "ordinary_profit":  _v(_fc.ordinary_profit),
            "net_income":       _v(_fc.net_income),
            "eps":              float(_fc.eps) if _fc.eps is not None else None,
            "revenue_yoy":      float(_fc.revenue_yoy) if _fc.revenue_yoy is not None else None,
            "op_profit_yoy":    float(_fc.op_profit_yoy) if _fc.op_profit_yoy is not None else None,
        }

    # Latest dividend forecast
    latest_dividend = (
        company.dividend_forecasts
        .order_by("-announced_at")
        .first()
    )

    # Fill valuation metrics now that forecast data is available
    price = float(company.share_price) if company.share_price else None
    _feps = latest_forecast["eps"] if latest_forecast else None
    _fdiv = None
    if latest_dividend:
        d = latest_dividend
        if d.annual_dividend:
            _fdiv = float(d.annual_dividend)
        else:
            interim = d.interim_dividend_paid or d.interim_dividend or 0
            year_end = d.year_end_dividend or 0
            total = interim + year_end
            if total:
                _fdiv = float(total)
    valuation.update({
        "forecast_eps":      _feps,
        "forecast_dividend": _fdiv,
        "per":          _ratio(price, _feps, 1),
        "pbr":          _ratio(price, _latest_bps, 2),
        "dividend_yield": round(_fdiv / price * 100, 2) if _fdiv and price else None,
    })

    return render(request, "listings/company_detail.html", {
        "company": company,
        "latest_snapshot": latest_snapshot,
        "major_shareholders": major_shareholders,
        "treasury_pct": treasury_pct,
        "shareholder_toggle_data": shareholder_toggle_data,
        "disclosures": disclosures,
        "total_disclosures": total_disclosures,
        "disclosure_batch": DISCLOSURE_BATCH,
        "fin_rows": fin_rows,
        "valuation": valuation,
        "latest_forecast": latest_forecast,
        "latest_dividend": latest_dividend,
    })


def company_disclosures(request, stock_code):
    company = get_object_or_404(Company, stock_code=stock_code)
    offset = int(request.GET.get("offset", DISCLOSURE_BATCH))
    disclosures = company.disclosures.order_by("-disclosed_date")[offset:offset + DISCLOSURE_BATCH]
    return render(request, "listings/_disclosures_rows.html", {
        "disclosures": disclosures,
    })

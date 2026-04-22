"""
tse_client.py
=============
TDnet iXBRL parser for 決算短信 (quarterly/annual earnings releases).

Downloads the XBRL ZIP from DisclosureRecord.xbrl_url, parses inline XBRL,
and upserts into Django financial models using (company, fiscal_year, fiscal_quarter)
as the natural key — merging with EDINET data when present.
"""

import io
import logging
import re
import time
import zipfile
from datetime import datetime
from decimal import Decimal

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Element maps  (tse-ed-t namespace local names → model field names)
# ---------------------------------------------------------------------------
# Monetary: raw yen values; stored in thousands (÷ 1000).
# Ratio: percentage values; stored as decimal ratio (÷ 100).
# Per-share / count: stored as-is.

TSE_INCOME_MONETARY = {
    # J-GAAP
    "NetSales": "revenue",
    "OperatingIncome": "operating_profit",
    "OrdinaryIncome": "ordinary_profit",
    "ProfitAttributableToOwnersOfParent": "net_income",
    # IFRS (ordinary_profit has no equivalent — omitted intentionally)
    "RevenueIFRS": "revenue",
    "OperatingIncomeIFRS": "operating_profit",
    "ProfitAttributableToOwnersOfParentIFRS": "net_income",
}
TSE_INCOME_RATIO = {
    # J-GAAP
    "NetIncomeToShareholdersEquityRatio": "roe",
    "OperatingIncomeToNetSalesRatio": "operating_margin",
    "ChangeInNetSales": "revenue_yoy",
    "ChangeInOperatingIncome": "op_profit_yoy",
    # IFRS
    "ProfitToEquityAttributableToOwnersOfParentRatioIFRS": "roe",
    "OperatingIncomeToRevenueRatioIFRS": "operating_margin",
    "ChangeInRevenueIFRS": "revenue_yoy",
    "ChangeInOperatingIncomeIFRS": "op_profit_yoy",
}
TSE_INCOME_PERSHARE = {
    # J-GAAP
    "NetIncomePerShare": "eps",
    # IFRS
    "BasicEarningsPerShareIFRS": "eps",
    "DilutedEarningsPerShareIFRS": "diluted_eps",
}

TSE_BALANCE_MONETARY = {
    # J-GAAP
    "TotalAssets": "total_assets",
    "NetAssets": "net_assets",
    "OwnersEquity": "owners_equity",
    "CashAndEquivalentsEndOfPeriod": "cash_and_equivalents",
    # IFRS
    "TotalAssetsIFRS": "total_assets",
    "TotalEquityIFRS": "net_assets",
    "EquityAttributableToOwnersOfParentIFRS": "owners_equity",
    "CashAndCashEquivalentsAtEndOfPeriodIFRS": "cash_and_equivalents",
}
TSE_BALANCE_RATIO = {
    # J-GAAP
    "CapitalAdequacyRatio": "equity_ratio",
    # IFRS
    "EquityAttributableToOwnersOfParentToTotalAssetsRatioIFRS": "equity_ratio",
}
TSE_BALANCE_PERSHARE = {
    # J-GAAP
    "NetAssetsPerShare": "book_value_per_share",
    # IFRS
    "EquityAttributableToOwnersOfParentPerShareIFRS": "book_value_per_share",
}
TSE_BALANCE_SHARES = {
    "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": "shares_issued",
    "NumberOfTreasuryStockAtTheEndOfFiscalYear": "treasury_shares",
}

# CF summary (annual only — from Summary file, tse-ed-t namespace)
TSE_CF_MONETARY = {
    # J-GAAP
    "CashFlowsFromOperatingActivities": "operating_cf",
    "CashFlowsFromInvestingActivities": "investing_cf",
    "CashFlowsFromFinancingActivities": "financing_cf",
    # IFRS
    "CashFlowsFromOperatingActivitiesIFRS": "operating_cf",
    "CashFlowsFromInvestingActivitiesIFRS": "investing_cf",
    "CashFlowsFromFinancingActivitiesIFRS": "financing_cf",
}

# CF attachment (Q2 and Annual — jppfs_cor namespace, plain contexts like EDINET)
ATTACHMENT_CF_MAP = {
    "NetCashProvidedByUsedInOperatingActivities": "operating_cf",
    "NetCashProvidedByUsedInInvestmentActivities": "investing_cf",
    "NetCashProvidedByUsedInFinancingActivities": "financing_cf",
}

# B/S attachment (all quarters — jppfs_cor namespace, plain contexts)
# Instant context: "CurrentYearInstant" for Annual, "CurrentQuarterInstant" for Q1/Q2/Q3
ATTACHMENT_BALANCE_MAP = {
    "CurrentAssets": "current_assets",
    "NoncurrentAssets": "non_current_assets",
    "Assets": "total_assets",
    "CurrentLiabilities": "current_liabilities",
    "Liabilities": "total_liabilities",
    "CashAndDeposits": "cash_and_equivalents",
    "ShortTermLoansPayable": "short_term_loans",
    "CommercialPapersLiabilities": "commercial_paper",
    "BondsPayable": "bonds_payable_current",
    "LongTermLoansPayable": "long_term_loans",
    "BondsPayableNoncurrent": "bonds_payable",
    "LeaseObligationsCL": "lease_obligations_current",
    "LeaseObligationsNCL": "lease_obligations_non_current",
    "NetAssets": "net_assets",
    "CapitalStock": "capital_stock",
    "RetainedEarnings": "retained_earnings",
    "NonControllingInterests": "non_controlling_interests",
}

# ---------------------------------------------------------------------------
# Forecast element maps  (same local names as actuals; context carries "ForecastMember")
# ---------------------------------------------------------------------------

TSE_FORECAST_MONETARY = {
    # J-GAAP
    "NetSales": "revenue",
    "OperatingIncome": "operating_profit",
    "OrdinaryIncome": "ordinary_profit",
    "ProfitAttributableToOwnersOfParent": "net_income",
    # IFRS
    "RevenueIFRS": "revenue",
    "OperatingIncomeIFRS": "operating_profit",
    "ProfitAttributableToOwnersOfParentIFRS": "net_income",
}
TSE_FORECAST_RATIO = {
    "ChangeInNetSales": "revenue_yoy",
    "ChangeInOperatingIncome": "op_profit_yoy",
    "ChangeInRevenueIFRS": "revenue_yoy",
    "ChangeInOperatingIncomeIFRS": "op_profit_yoy",
}
TSE_FORECAST_PERSHARE = {
    "NetIncomePerShare": "eps",
    "BasicEarningsPerShareIFRS": "eps",
}


INCOME_FIELDS = set(TSE_INCOME_MONETARY.values()) | set(TSE_INCOME_RATIO.values()) | set(TSE_INCOME_PERSHARE.values())
BALANCE_FIELDS = (set(TSE_BALANCE_MONETARY.values()) | set(TSE_BALANCE_RATIO.values())
                  | set(TSE_BALANCE_PERSHARE.values()) | set(TSE_BALANCE_SHARES.values())
                  | set(ATTACHMENT_BALANCE_MAP.values()))
CF_FIELDS = set(TSE_CF_MONETARY.values()) | set(ATTACHMENT_CF_MAP.values())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def detect_report_type(title: str):
    """
    Parse a 決算短信 title like '2026年3月期　第1四半期決算短信[日本基準](連結)'
    and return (report_type, fiscal_quarter, fiscal_year).
    """
    from financials.models import FinancialReport

    m = re.search(r'(\d{4})年', title)
    fiscal_year = int(m.group(1)) if m else None

    # Full-width and half-width quarter numbers
    if re.search(r'第[1１]四半期', title):
        return FinancialReport.ReportType.Q1, 1, fiscal_year
    elif re.search(r'第[2２]四半期|中間', title):
        return FinancialReport.ReportType.Q2, 2, fiscal_year
    elif re.search(r'第[3３]四半期', title):
        return FinancialReport.ReportType.Q3, 3, fiscal_year
    else:
        return FinancialReport.ReportType.ANNUAL, 4, fiscal_year


def _context_prefixes(fiscal_quarter: int) -> tuple[str, str]:
    """Return (duration_prefix, instant_prefix) for the given quarter."""
    if fiscal_quarter == 4:
        return "CurrentYearDuration", "CurrentYearInstant"
    return f"CurrentAccumulatedQ{fiscal_quarter}Duration", f"CurrentAccumulatedQ{fiscal_quarter}Instant"


def _extract_ixbrl(zf: zipfile.ZipFile, fname: str) -> list[tuple]:
    """
    Extract all ix:nonFraction elements from an iXBRL HTML file.
    Returns list of (local_name, context_id, Decimal_value, scale_int).
    """
    with zf.open(fname) as f:
        content = f.read().decode("utf-8", errors="replace")
    pattern = r'<ix:nonfraction\s([^>]+?)>([\d,.\-]+)</ix:nonfraction>'
    results = []
    for m in re.finditer(pattern, content, re.IGNORECASE):
        attrs, raw_val = m.group(1), m.group(2).replace(",", "")
        name_m = re.search(r'name="([^"]+)"', attrs)
        ctx_m = re.search(r'contextRef="([^"]+)"', attrs)
        scale_m = re.search(r'scale="([^"]+)"', attrs)
        if not (name_m and ctx_m):
            continue
        try:
            val = Decimal(raw_val)
        except Exception:
            continue
        scale = int(scale_m.group(1)) if scale_m else 0
        local = name_m.group(1).split(":")[-1]
        results.append((local, ctx_m.group(1), val, scale))
    return results


def _extract_period_end(zf: zipfile.ZipFile) -> str | None:
    """Extract the reporting period_end date.

    1. Attachment XSD filename  (tse-...-YYYY-MM-DD-NN-YYYY-MM-DD.xsd)
    2. Summary XSD filename     (same pattern)
    3. xbrli:instant inside the iXBRL — the CurrentYearInstant / CurrentQuarterInstant context
    """
    DATE_PAT = re.compile(r'-(20\d\d-\d\d-\d\d)-\d\d-20\d\d')
    attachment_date = summary_date = None
    for name in zf.namelist():
        if not name.endswith(".xsd"):
            continue
        m = DATE_PAT.search(name)
        if not m:
            continue
        if "Attachment" in name and attachment_date is None:
            attachment_date = m.group(1)
        elif "Summary" in name and summary_date is None:
            summary_date = m.group(1)
    if attachment_date or summary_date:
        return attachment_date or summary_date

    # Fallback: parse the instant date from XBRL context definitions in any iXBRL file.
    # Look for CurrentYearInstant or CurrentQuarterInstant context.
    INSTANT_CTX = re.compile(
        r'id="(CurrentYearInstant|CurrentQuarterInstant|InterimInstant)"[^>]*>.*?'
        r'<xbrli:instant>(20\d\d-\d\d-\d\d)</xbrli:instant>',
        re.DOTALL,
    )
    for name in zf.namelist():
        if not name.endswith((".htm", ".html", ".xbrl")):
            continue
        try:
            with zf.open(name) as f:
                content = f.read().decode("utf-8", errors="replace")
        except Exception:
            continue
        m = INSTANT_CTX.search(content)
        if m:
            return m.group(2)
    return None


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def parse_tse_xbrl(zf: zipfile.ZipFile, fiscal_quarter: int, verbose: bool = False) -> dict:
    """
    Parse TDnet iXBRL ZIP for the given fiscal_quarter (1–4).
    Returns a flat dict {model_field: value} ready to upsert.

    Monetary values are stored in thousands of yen (千円).
    Ratio/percentage values are stored as decimal ratios (e.g. 0.107 for 10.7%).
    Per-share values (EPS, BPS) are stored in yen as Decimal.
    """
    dur_prefix, inst_prefix = _context_prefixes(fiscal_quarter)

    all_monetary = {**TSE_INCOME_MONETARY, **TSE_BALANCE_MONETARY, **TSE_CF_MONETARY}
    all_ratio = {**TSE_INCOME_RATIO, **TSE_BALANCE_RATIO}
    all_pershare = {**TSE_INCOME_PERSHARE, **TSE_BALANCE_PERSHARE}

    values: dict = {}

    def apply(elements):
        for local, ctx, val, scale in elements:
            if "NonConsolidated" in ctx:
                continue
            if "ConsolidatedMember" not in ctx or "ResultMember" not in ctx:
                continue
            if "Prior" in ctx or "Next" in ctx or "Forecast" in ctx:
                continue
            is_dur = dur_prefix in ctx
            is_inst = inst_prefix in ctx
            if not (is_dur or is_inst):
                continue

            if local in all_monetary:
                field = all_monetary[local]
                yen = val * (Decimal(10) ** scale)
                values[field] = int(yen // 1000)
                if verbose:
                    print(f"    {local} → {field} = {values[field]:,} 千円")
            elif local in all_ratio:
                field = all_ratio[local]
                values[field] = val / 100
                if verbose:
                    print(f"    {local} → {field} = {values[field]}")
            elif local in all_pershare:
                field = all_pershare[local]
                values[field] = val
                if verbose:
                    print(f"    {local} → {field} = {val} 円/株")
            elif local in TSE_BALANCE_SHARES:
                field = TSE_BALANCE_SHARES[local]
                values[field] = int(val * (Decimal(10) ** scale))
                if verbose:
                    print(f"    {local} → {field} = {values[field]:,} 株")

    # Summary file (all quarters)
    for fname in zf.namelist():
        if "Summary" in fname and fname.endswith("-ixbrl.htm"):
            if verbose:
                print(f"  Summary: {fname}")
            apply(_extract_ixbrl(zf, fname))

    # B/S Attachment (all quarters).
    # Uses jppfs_cor element names and plain instant contexts.
    # Annual=CurrentYearInstant, Q2/半期=InterimInstant, Q1/Q3=CurrentQuarterInstant
    if fiscal_quarter == 4:
        bs_ctx = "CurrentYearInstant"
    elif fiscal_quarter == 2:
        bs_ctx = "InterimInstant"
    else:
        bs_ctx = "CurrentQuarterInstant"
    for fname in zf.namelist():
        if "Attachment" in fname and fname.endswith("-ixbrl.htm") and "bs" in fname.lower():
            if verbose:
                print(f"  B/S attachment: {fname}")
            for local, ctx, val, scale in _extract_ixbrl(zf, fname):
                if ctx != bs_ctx:
                    continue
                if local in ATTACHMENT_BALANCE_MAP:
                    field = ATTACHMENT_BALANCE_MAP[local]
                    yen = val * (Decimal(10) ** scale)
                    values[field] = int(yen // 1000)
                    if verbose:
                        print(f"    {local} → {field} = {values[field]:,} 千円")

    # CF Attachment (Q2 and Annual only).
    # Uses jppfs_cor element names and plain contexts (no ConsolidatedMember/ResultMember).
    if fiscal_quarter in (2, 4):
        cf_ctx = "CurrentYearDuration" if fiscal_quarter == 4 else "InterimDuration"
        for fname in zf.namelist():
            if "Attachment" in fname and fname.endswith("-ixbrl.htm") and "cf" in fname.lower():
                if verbose:
                    print(f"  CF attachment: {fname}")
                for local, ctx, val, scale in _extract_ixbrl(zf, fname):
                    if ctx != cf_ctx:
                        continue
                    if local in ATTACHMENT_CF_MAP:
                        field = ATTACHMENT_CF_MAP[local]
                        yen = val * (Decimal(10) ** scale)
                        values[field] = int(yen // 1000)
                        if verbose:
                            print(f"    {local} → {field} = {values[field]:,} 千円")

    # Derive owners_equity from B/S attachment data if Summary didn't provide it.
    # 自己資本 = 純資産合計 − 非支配株主持分
    if values.get("owners_equity") is None:
        net = values.get("net_assets")
        nci = values.get("non_controlling_interests") or 0
        if net is not None:
            values["owners_equity"] = net - nci
            if verbose:
                print(f"  [derived] owners_equity = {values['owners_equity']:,} 千円")

    # Calculate BPS for quarterly reports where the Summary doesn't include it.
    # BPS (円) = 自己資本 (千円) × 1,000 ÷ (発行済株式数 − 自己株式数)
    if values.get("book_value_per_share") is None:
        equity = values.get("owners_equity")
        issued = values.get("shares_issued")
        treasury = values.get("treasury_shares") or 0
        float_shares = issued - treasury if issued is not None else None
        if equity is not None and float_shares:
            values["book_value_per_share"] = Decimal(equity * 1000) / float_shares
            if verbose:
                print(f"  [derived] book_value_per_share = {values['book_value_per_share']:.2f} 円/株")

    return values


# ---------------------------------------------------------------------------
# Forecast parser
# ---------------------------------------------------------------------------

def parse_forecast_xbrl(zf: zipfile.ZipFile, verbose: bool = False) -> tuple[dict, dict]:
    """
    Extract financial and dividend forecasts from the TDnet iXBRL Summary file.
    Returns (fin_values, div_values) — dicts with ForecastRecord / DividendForecast
    field names as keys.

    Forecast contexts carry "ForecastMember" instead of "ResultMember".
    Financial forecasts use CurrentYearDuration; dividend forecasts use
    CurrentYearInstant (both consolidated).
    """
    fin_values: dict = {}
    div_values: dict = {}

    # Dividend type is encoded as a context member, not in the element name.
    # e.g. CurrentYearDuration_SecondQuarterMember_NonConsolidatedMember_ForecastMember
    DIVIDEND_MEMBER_MAP = {
        "SecondQuarterMember": "interim_dividend",   # 中間配当 (H1)
        "YearEndMember":       "year_end_dividend",  # 期末配当
        "AnnualMember":        "annual_dividend",    # 年間合計
    }

    for fname in zf.namelist():
        if "Summary" not in fname or not fname.endswith("-ixbrl.htm"):
            continue
        if verbose:
            print(f"  [forecast] parsing: {fname}")
        for local, ctx, val, scale in _extract_ixbrl(zf, fname):
            if "CurrentYearDuration" not in ctx:
                continue

            is_forecast = "ForecastMember" in ctx
            is_result = "ResultMember" in ctx
            if not (is_forecast or is_result):
                continue

            # Financial forecast — consolidated ForecastMember only.
            # Note: "ConsolidatedMember" is a substring of "NonConsolidatedMember",
            # so we must explicitly exclude the Non- variant first.
            if is_forecast and "NonConsolidated" not in ctx and "ConsolidatedMember" in ctx:
                if local in TSE_FORECAST_MONETARY:
                    yen = val * (Decimal(10) ** scale)
                    fin_values[TSE_FORECAST_MONETARY[local]] = int(yen // 1000)
                    if verbose:
                        print(f"    [forecast:fin] {local} → {TSE_FORECAST_MONETARY[local]} = {int(yen//1000):,}")
                elif local in TSE_FORECAST_RATIO:
                    fin_values[TSE_FORECAST_RATIO[local]] = val / 100
                    if verbose:
                        print(f"    [forecast:fin] {local} → {TSE_FORECAST_RATIO[local]} = {val/100}")
                elif local in TSE_FORECAST_PERSHARE:
                    fin_values[TSE_FORECAST_PERSHARE[local]] = val
                    if verbose:
                        print(f"    [forecast:fin] {local} → {TSE_FORECAST_PERSHARE[local]} = {val}")

            # Dividends — DividendPerShare, NonConsolidated context.
            # ForecastMember → forecast fields; ResultMember → _paid fields.
            # Dividend type (Interim / YearEnd / Annual) is encoded as a context member.
            if local == "DividendPerShare" and "NonConsolidated" in ctx:
                for member, base_field in DIVIDEND_MEMBER_MAP.items():
                    if member in ctx:
                        field = base_field if is_forecast else base_field + "_paid"
                        div_values[field] = val * (Decimal(10) ** scale)
                        if verbose:
                            tag = "forecast" if is_forecast else "actual"
                            print(f"    [forecast:div] DividendPerShare ({member}, {tag}) → {field} = {val}")
                        break

    if verbose:
        print(f"  [forecast] fin={fin_values}  div={div_values}")
    return fin_values, div_values


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class TseClient:
    """Downloads and stores TDnet 決算短信 XBRL data."""

    def __init__(self, throttle: float = 0.5):
        self.session = requests.Session()
        self.throttle = throttle

    def fetch_and_store(self, disclosure, verbose: bool = False) -> tuple:
        """
        Full pipeline for one DisclosureRecord:
          download ZIP → parse iXBRL → upsert FinancialReport + sub-statements.

        Uses (company, fiscal_year, fiscal_quarter) as the natural key, so data
        merges with any EDINET record for the same period.

        Returns (report, values); both may be None on failure.
        """
        from financials.models import FinancialReport, IncomeStatement, BalanceSheet, CashFlowStatement, ForecastRecord, DividendForecast
        from financials.edinet_client import _upsert

        title = disclosure.title
        report_type, fiscal_quarter, fiscal_year = detect_report_type(title)

        if verbose:
            print(f"  title: {title}")
            print(f"  → type={report_type}, Q={fiscal_quarter}, FY={fiscal_year}")

        if not fiscal_year:
            logger.warning("Cannot determine fiscal_year from: %s", title)
            return None, None

        # Download
        try:
            resp = self.session.get(disclosure.xbrl_url, timeout=60)
            resp.raise_for_status()
            time.sleep(self.throttle)
            zf = zipfile.ZipFile(io.BytesIO(resp.content))
        except Exception as e:
            logger.error("Download failed for %s: %s", disclosure.xbrl_url, e)
            return None, None

        period_end = _extract_period_end(zf)
        if verbose:
            print(f"  period_end={period_end}")
        if period_end is None:
            logger.warning("Cannot determine period_end for %s — skipping", disclosure.xbrl_url)
            return None, None

        filed_at = None
        if disclosure.disclosed_date:
            filed_at = timezone.make_aware(datetime.combine(disclosure.disclosed_date, datetime.min.time()))

        # Upsert FinancialReport by natural key
        report, created = FinancialReport.objects.update_or_create(
            company=disclosure.company,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            defaults=dict(
                period_end=period_end,
                report_type=report_type,
                is_consolidated=True,
                filed_at=filed_at,
            ),
        )
        logger.info("%s FinancialReport %s (TDnet)", "Created" if created else "Updated", report)

        # Parse iXBRL
        try:
            values = parse_tse_xbrl(zf, fiscal_quarter, verbose=verbose)
            if verbose:
                print(f"  fields parsed: {list(values.keys())}")
        except Exception as e:
            logger.error("Parse failed for %s: %s", disclosure.xbrl_url, e)
            return report, None

        # Upsert sub-statements (only touch fields we actually parsed)
        _upsert_fields(IncomeStatement, report, values, INCOME_FIELDS)
        _upsert_fields(BalanceSheet, report, values, BALANCE_FIELDS)
        _upsert_fields(CashFlowStatement, report, values, CF_FIELDS)

        # Forecasts — always insert a new row to preserve revision history
        fin_fc, div_fc = parse_forecast_xbrl(zf, verbose=verbose)
        if fin_fc:
            _, created = ForecastRecord.objects.update_or_create(
                source_report=report,
                defaults=dict(
                    company=disclosure.company,
                    announced_at=disclosure.disclosed_date,
                    target_fiscal_year=fiscal_year,
                    target_fiscal_quarter=4,
                    **fin_fc,
                ),
            )
            if verbose:
                print(f"  {'Created' if created else 'Updated'} ForecastRecord for FY{fiscal_year}")
        if div_fc:
            _, created = DividendForecast.objects.update_or_create(
                source_report=report,
                defaults=dict(
                    company=disclosure.company,
                    announced_at=disclosure.disclosed_date,
                    target_fiscal_year=fiscal_year,
                    **div_fc,
                ),
            )
            if verbose:
                print(f"  {'Created' if created else 'Updated'} DividendForecast for FY{fiscal_year}")

        logger.info("Stored TDnet financials for %s", report)
        return report, values


def _upsert_fields(model_cls, report, values: dict, field_names: set) -> None:
    """Create or update a financial sub-statement for the given set of field names."""
    kwargs = {f: values[f] for f in field_names if f in values}
    if not kwargs:
        return
    obj, created = model_cls.objects.update_or_create(report=report, defaults=kwargs)
    logger.debug("%s %s (TDnet)", "Created" if created else "Updated", obj)

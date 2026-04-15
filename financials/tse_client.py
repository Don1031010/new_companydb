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
    "OwnersEquity": "shareholders_equity",
    "CashAndEquivalentsEndOfPeriod": "cash_and_equivalents",
    # IFRS
    "TotalAssetsIFRS": "total_assets",
    "TotalEquityIFRS": "net_assets",
    "EquityAttributableToOwnersOfParentIFRS": "shareholders_equity",
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
    "ShareholdersEquity": "shareholders_equity",
}

INCOME_FIELDS = set(TSE_INCOME_MONETARY.values()) | set(TSE_INCOME_RATIO.values()) | set(TSE_INCOME_PERSHARE.values())
BALANCE_FIELDS = (set(TSE_BALANCE_MONETARY.values()) | set(TSE_BALANCE_RATIO.values())
                  | set(TSE_BALANCE_PERSHARE.values()) | set(ATTACHMENT_BALANCE_MAP.values()))
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
    pattern = r'<ix:nonFraction\s([^>]+?)>([\d,.\-]+)</ix:nonFraction>'
    results = []
    for m in re.finditer(pattern, content):
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
    """Extract the reporting period_end date from the Attachment XSD filename."""
    for name in zf.namelist():
        if "Attachment" in name and name.endswith(".xsd"):
            # e.g. tse-acedjpfr-13010-2025-03-31-01-2025-05-12.xsd
            m = re.search(r'-(20\d\d-\d\d-\d\d)-\d\d-20\d\d', name)
            if m:
                return m.group(1)
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

    return values


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
        from financials.models import FinancialReport, IncomeStatement, BalanceSheet, CashFlowStatement
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

        logger.info("Stored TDnet financials for %s", report)
        return report, values


def _upsert_fields(model_cls, report, values: dict, field_names: set) -> None:
    """Create or update a financial sub-statement for the given set of field names."""
    kwargs = {f: values[f] for f in field_names if f in values}
    if not kwargs:
        return
    obj, created = model_cls.objects.update_or_create(report=report, defaults=kwargs)
    logger.debug("%s %s (TDnet)", "Created" if created else "Updated", obj)

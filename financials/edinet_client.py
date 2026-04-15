"""
edinet_client.py
================
EDINET API v2 client for fetching financial statement data for TSE-listed companies.

Usage (standalone):
    client = EdinetClient()
    docs = client.get_docs_for_company("E02166", year=2024)  # E02166 = Toyota
    client.fetch_and_store(docs[0])

Usage as Django management command:
    python manage.py fetch_edinet --edinet-code E02166 --year 2024
"""

import io
import logging
import time
import zipfile
from datetime import date, timedelta
from decimal import Decimal

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

EDINET_BASE = "https://disclosure.edinet-fsa.go.jp/api/v2"

# XBRL element names → our model fields
# These are the standard jpcrp (Japan Taxonomy) element local names.
INCOME_XBRL_MAP = {
    "NetSales": "revenue",
    "GrossProfit": "gross_profit",
    "OperatingIncome": "operating_profit",                                      # 営業利益
    "OrdinaryIncome": "ordinary_profit",                                        # 経常利益
    "ProfitLossAttributableToOwnersOfParent": "net_income",                     # 親会社株主に帰属する当期純利益
    "ResearchAndDevelopmentExpensesSGA": "rd_expenses",                         # 研究開発費
    "BasicEarningsLossPerShareSummaryOfBusinessResults": "eps",                 # 1株当たり純利益（公表値）
    "DilutedEarningsPerShareSummaryOfBusinessResults": "diluted_eps",           # 希薄化後EPS（公表値）
    "RateOfReturnOnEquitySummaryOfBusinessResults": "roe",                      # 自己資本利益率（公表値）
}
BALANCE_XBRL_MAP = {
    "Assets": "total_assets",
    "CurrentAssets": "current_assets",
    "NoncurrentAssets": "non_current_assets",
    "CashAndCashEquivalents": "cash_and_equivalents",
    "Liabilities": "total_liabilities",
    "CurrentLiabilities": "current_liabilities",
    "NetAssets": "net_assets",
    "ShareholdersEquity": "shareholders_equity",
    "EquityToAssetRatioSummaryOfBusinessResults": "equity_ratio",       # 自己資本比率
    "NetAssetsPerShareSummaryOfBusinessResults": "book_value_per_share", # 1株当たり純資産
    # Interest-bearing debt components
    "ShortTermLoansPayable": "short_term_loans",                        # 短期借入金
    "CommercialPapersLiabilities": "commercial_paper",                  # CP
    "BondsPayable": "bonds_payable_current",                            # 社債（流動）
    "LongTermLoansPayable": "long_term_loans",                          # 長期借入金
    "BondsPayableNoncurrent": "bonds_payable",                          # 社債（固定）
    "LeaseObligationsCL": "lease_obligations_current",                  # リース債務（流動）
    "LeaseObligationsNCL": "lease_obligations_non_current",             # リース債務（固定）
}
CF_XBRL_MAP = {
    "NetCashProvidedByUsedInOperatingActivities": "operating_cf",
    "NetCashProvidedByUsedInInvestmentActivities": "investing_cf",              # note: Investment not Investing
    "NetCashProvidedByUsedInFinancingActivities": "financing_cf",
    "CapitalExpendituresOverviewOfCapitalExpendituresEtc": "capex",             # 設備投資額（設備投資等の概要）
    "DepreciationAndAmortizationOpeCF": "depreciation",                        # 減価償却費
}


class EdinetClient:
    """Thin wrapper around EDINET API v2."""

    def __init__(self, api_key: str | None = None, throttle: float = 0.5):
        """
        api_key: required for some endpoints in the paid tier.
                 Free tier works without it for document lists + XBRL bulk.
        throttle: seconds to sleep between requests (be polite to FSA servers).
        """
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        if api_key:
            self.session.headers["Ocp-Apim-Subscription-Key"] = api_key
        self.throttle = throttle

    # ------------------------------------------------------------------
    # 1. Document list
    # ------------------------------------------------------------------

    def get_docs_for_date(self, target_date: date, doc_type: int = 2) -> list[dict]:
        """
        Returns all filings submitted on target_date.
        doc_type=2 → 有価証券報告書 and 決算短信 (most financial filings)
        doc_type=1 → metadata only (no document content)
        """
        url = f"{EDINET_BASE}/documents.json"
        params = {"date": target_date.isoformat(), "type": doc_type}
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        time.sleep(self.throttle)
        return data.get("results", [])

    def get_docs_for_company(
        self,
        edinet_code: str,
        year: int,
        form_codes: tuple[str, ...] = ("030000",  # 有価証券報告書
                                        "043A00",  # 半期報告書（2024年制度改正後）
                                        "043000",  # 四半期報告書 Q1/Q3（旧制度、2024年以前）
                                        "043001"), # 四半期報告書 Q2（旧制度）
    ) -> list[dict]:
        """
        Looks up filings for one EDINET code using the cached EDINETDocument table
        first, falling back to a live API scan for any dates not yet cached.

        Tip: Run fetch_shareholders (which populates EDINETDocument) before this
        command to avoid redundant API calls.
        """
        from listings.models import EDINETDocument

        # Query the local cache first
        cached_docs = EDINETDocument.objects.filter(
            edinet_code=edinet_code,
            form_code__in=form_codes,
            submit_date__year=year,
            withdrawn=False,
        ).values("doc_id", "form_code", "period_end", "submit_date", "description")

        results = [
            {
                "docID": d["doc_id"],
                "edinetCode": edinet_code,
                "formCode": d["form_code"],
                "periodEnd": d["period_end"].isoformat() if d["period_end"] else None,
                "submitDateTime": str(d["submit_date"]),
                "docDescription": d["description"],
            }
            for d in cached_docs
        ]

        if results:
            logger.info(
                "Found %d filings for %s in %d (from cache)",
                len(results), edinet_code, year,
            )
            return results

        # Cache miss — fall back to brute-force API scan
        logger.info("Cache miss for %s %d — scanning EDINET API day by day", edinet_code, year)
        start = date(year, 1, 1)
        # Never scan past today — future dates have no filings
        end = min(date(year, 12, 31), date.today())
        if start > end:
            logger.info("No dates to scan for %s %d (year is in the future)", edinet_code, year)
            return results
        current = start
        # Only weekdays: EDINET has no filings on Sat(5) or Sun(6)
        scan_days = [(start + timedelta(days=i)) for i in range((end - start).days + 1)
                     if (start + timedelta(days=i)).weekday() < 5]
        total_days = len(scan_days)
        checked = 0

        for current in scan_days:
            try:
                docs = self.get_docs_for_date(current, doc_type=2)
                for doc in docs:
                    if (
                        doc.get("edinetCode") == edinet_code
                        and doc.get("formCode") in form_codes
                    ):
                        results.append(doc)
            except requests.HTTPError as e:
                logger.warning("HTTP error on %s: %s", current, e)
            checked += 1
            if checked % 30 == 0:
                logger.info(
                    "  scanning %s: %d/%d days checked, %d filing(s) found so far",
                    edinet_code, checked, total_days, len(results),
                )

        logger.info("Found %d filings for %s in %d", len(results), edinet_code, year)
        return results

    # ------------------------------------------------------------------
    # 2. Download XBRL bulk package
    # ------------------------------------------------------------------

    def download_xbrl_zip(self, doc_id: str) -> zipfile.ZipFile | None:
        """
        Downloads the XBRL bulk package (type=5) for a given document ID.
        Returns an in-memory ZipFile, or None if the document has no XBRL package.
        """
        url = f"{EDINET_BASE}/documents/{doc_id}"
        resp = self.session.get(url, params={"type": 5}, timeout=60, stream=True)
        resp.raise_for_status()
        time.sleep(self.throttle)
        content_type = resp.headers.get("Content-Type", "")
        if "zip" not in content_type and "octet-stream" not in content_type:
            try:
                error_detail = resp.json()
            except Exception:
                error_detail = resp.text[:200]
            logger.warning(
                "No XBRL zip for %s (Content-Type: %s) — EDINET response: %s",
                doc_id, content_type, error_detail,
            )
            return None
        return zipfile.ZipFile(io.BytesIO(resp.content))

    # ------------------------------------------------------------------
    # 3. Parse XBRL
    # ------------------------------------------------------------------

    @staticmethod
    def parse_xbrl(zf: zipfile.ZipFile, verbose: bool = False) -> dict:
        """
        Extracts financial figures from the XBRL files inside the zip.
        Returns a flat dict: { 'revenue': 1234567, 'operating_profit': ... }

        The XBRL namespace prefix is typically 'jpcrp_cor' or 'jppfs_cor'
        (Japanese GAAP primary financial statements taxonomy).
        """
        try:
            from lxml import etree
        except ImportError:
            raise ImportError("pip install lxml  # required for XBRL parsing")

        values: dict = {}
        all_maps = {**INCOME_XBRL_MAP, **BALANCE_XBRL_MAP, **CF_XBRL_MAP}
        target_elements = set(all_maps.keys())

        has_xbrl = any(n.endswith(".xbrl") for n in zf.namelist())
        csv_files = [n for n in zf.namelist() if n.endswith(".csv") and "XBRL_TO_CSV" in n]

        if not has_xbrl and csv_files:
            return EdinetClient._parse_xbrl_csv(zf, csv_files, verbose)

        for name in zf.namelist():
            if not name.endswith(".xbrl"):
                continue
            with zf.open(name) as f:
                tree = etree.parse(f)
            root = tree.getroot()

            if verbose:
                # Print a sample of unique element local names to help diagnose mismatches
                sample = set()
                for elem in root.iter():
                    sample.add(etree.QName(elem.tag).localname)
                print(f"  [{name}] sample elements (first 30): {sorted(sample)[:30]}")

            for elem in root.iter():
                local = etree.QName(elem.tag).localname
                if local not in target_elements:
                    continue
                # Prefer consolidated (連結) over standalone: context typically
                # contains "ConsolidatedInstant" or "ConsolidatedDuration"
                context_ref = elem.get("contextRef", "")
                is_consolidated = "Consolidated" in context_ref
                text = (elem.text or "").strip()
                if not text:
                    continue
                try:
                    raw = Decimal(text)
                except Exception:
                    continue

                field = all_maps[local]
                # Store consolidated if available, else standalone
                if field not in values or is_consolidated:
                    values[field] = int(raw) if raw == raw.to_integral_value() else raw

        return values

    @staticmethod
    def _parse_xbrl_csv(zf: zipfile.ZipFile, csv_files: list[str], verbose: bool = False) -> dict:
        """
        Parse EDINET XBRL_TO_CSV files (UTF-16 TSV).
        Column layout: 要素ID | 項目名 | コンテキストID | 相対年度 | 連結・個別 | 期間・時点 | ユニットID | 単位 | 値
        """
        import csv
        import io as _io

        all_maps = {**INCOME_XBRL_MAP, **BALANCE_XBRL_MAP, **CF_XBRL_MAP}
        target_elements = set(all_maps.keys())
        values: dict = {}
        values_priority: dict = {}  # tracks best priority seen per field

        # Prefer the main financial report CSV (jpcrp / jppfs), skip audit files (jpaud)
        financial_csvs = [n for n in csv_files if not n.split("/")[-1].startswith("jpaud")]
        if not financial_csvs:
            financial_csvs = csv_files

        for csv_name in financial_csvs:
            if verbose:
                print(f"  parsing CSV: {csv_name}")
            with zf.open(csv_name) as raw:
                reader = csv.reader(
                    _io.TextIOWrapper(raw, encoding="utf-16"),
                    delimiter="\t",
                )
                next(reader, None)  # skip header row
                for row in reader:
                    if len(row) < 9:
                        continue
                    element_id    = row[0].strip('"')   # e.g. "jpcrp_cor:NetSales"
                    label_ja      = row[1].strip('"')   # Japanese label
                    context_id    = row[2].strip('"')   # e.g. "CurrentYearDuration"
                    fiscal_period = row[3].strip('"')   # 当期/前期/etc.
                    consolidated  = row[4].strip('"')   # 連結 / 個別 / その他
                    raw_value     = row[8].strip('"')

                    # In verbose mode, dump all numeric consolidated current-period rows
                    # so we can identify correct element names for unmapped fields
                    if verbose and consolidated == "連結" and fiscal_period in ("当期", "当期末", "当中間期", "当中間期末"):
                        try:
                            Decimal(raw_value.replace(",", ""))
                            local_name = element_id.split(":")[-1] if ":" in element_id else element_id
                            if local_name not in target_elements:
                                print(f"  [unmapped] {local_name} ({label_ja}) = {raw_value}")
                        except Exception:
                            pass

                    # Extract local name from "namespace:LocalName"
                    local = element_id.split(":")[-1] if ":" in element_id else element_id
                    if local not in target_elements:
                        continue
                    if not raw_value or raw_value in ("－", "-", ""):
                        continue
                    try:
                        num = Decimal(raw_value.replace(",", ""))
                    except Exception:
                        continue

                    # Only accept "bare" contexts (no underscore = no segment/component suffix).
                    # e.g. accept "CurrentYearDuration", reject "CurrentYearDuration_MarineSegmentMember"
                    # For SummaryOfBusinessResults this also filters out _NonConsolidatedMember.
                    if "_" in context_id:
                        continue

                    # Only accept current-period rows.
                    # Annual reports use 当期/当期末; interim (半期) reports use 当中間期/当中間期末.
                    if fiscal_period not in ("当期", "当期末", "当中間期", "当中間期末"):
                        continue

                    # Skip standalone-only rows; prefer 連結 over その他
                    if consolidated == "個別":
                        continue

                    field = all_maps[local]
                    if consolidated == "連結":
                        priority = 2
                    else:  # その他 (SummaryOfBusinessResults consolidated section)
                        priority = 1

                    if priority > values_priority.get(field, -1):
                        values[field] = int(num) if num == num.to_integral_value() else num
                        values_priority[field] = priority
                    if verbose:
                        print(f"    {local} → {field} = {num}  [連結={consolidated}, ctx={context_id}, 年度={fiscal_period}]")

        if verbose:
            print(f"  final values: {values}")
        return values

    # ------------------------------------------------------------------
    # 4. Store to Django models
    # ------------------------------------------------------------------

    def fetch_and_store(self, doc_meta: dict, verbose: bool = False) -> tuple:
        """
        Full pipeline: download → parse → upsert into Django models.
        doc_meta is one entry from get_docs_for_company().
        Returns (report, values) for inspection; both may be None on failure.
        """
        from financials.models import FinancialReport, IncomeStatement, BalanceSheet, CashFlowStatement
        from listings.models import Company

        edinet_code = doc_meta["edinetCode"]
        doc_id = doc_meta["docID"]
        period_end_str = doc_meta.get("periodEnd")  # "YYYY-MM-DD"

        # submitDateTime arrives as a naive string e.g. "2025-06-25 00:00:00"
        submitted_at = None
        raw_dt = doc_meta.get("submitDateTime")
        if raw_dt:
            from datetime import datetime
            try:
                submitted_at = timezone.make_aware(datetime.fromisoformat(raw_dt))
            except (ValueError, TypeError):
                pass

        try:
            company = Company.objects.get(edinet_code=edinet_code)
        except Company.DoesNotExist:
            logger.warning("Company not found for EDINET code %s — skipping", edinet_code)
            return None, None

        # Determine report type from formCode
        form_code = doc_meta.get("formCode", "")
        desc = doc_meta.get("docDescription", "")
        if form_code == "030000":
            report_type = FinancialReport.ReportType.ANNUAL
            fiscal_quarter = 4
        elif form_code == "043A00":
            # 半期報告書 — always the 6-month (Q2) point
            report_type, fiscal_quarter = FinancialReport.ReportType.Q2, 2
        else:
            # 四半期報告書（旧制度）: quarter from docDescription
            if "第1四半期" in desc:
                report_type, fiscal_quarter = FinancialReport.ReportType.Q1, 1
            elif "第2四半期" in desc or "中間" in desc:
                report_type, fiscal_quarter = FinancialReport.ReportType.Q2, 2
            elif "第3四半期" in desc:
                report_type, fiscal_quarter = FinancialReport.ReportType.Q3, 3
            else:
                report_type, fiscal_quarter = FinancialReport.ReportType.ANNUAL, 4

        fiscal_year = int(period_end_str[:4]) if period_end_str else None

        # Upsert by natural key (company, fiscal_year, fiscal_quarter) so EDINET and
        # TDnet records for the same period merge into one FinancialReport row.
        report, created = FinancialReport.objects.update_or_create(
            company=company,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            defaults=dict(
                edinet_doc_id=doc_id,
                period_end=period_end_str,
                report_type=report_type,
                is_consolidated=True,
                filed_at=submitted_at,
            ),
        )
        logger.info("%s FinancialReport %s", "Created" if created else "Updated", report)

        # Download + parse
        try:
            zf = self.download_xbrl_zip(doc_id)
            if zf is None:
                return report, {}
            if verbose:
                print(f"  zip contents: {zf.namelist()}")
            values = self.parse_xbrl(zf, verbose=verbose)
            if verbose:
                print(f"  parsed values: {values}")
        except Exception as e:
            print(f"  ERROR download/parse XBRL for {doc_id}: {e}")
            logger.error("Failed to download/parse XBRL for %s: %s", doc_id, e)
            return report, None

        # Upsert sub-statements
        _upsert(IncomeStatement, report, values, INCOME_XBRL_MAP)
        _upsert(BalanceSheet, report, values, BALANCE_XBRL_MAP)
        _upsert(CashFlowStatement, report, values, CF_XBRL_MAP)
        logger.info("Stored financials for %s", report)
        return report, values


def _upsert(model_cls, report, values: dict, xbrl_map: dict) -> None:
    """Helper: create or update a financial sub-statement."""
    kwargs = {field: values[field] for field in xbrl_map.values() if field in values}
    if not kwargs:
        return
    obj, created = model_cls.objects.update_or_create(report=report, defaults=kwargs)
    logger.debug("%s %s", "Created" if created else "Updated", obj)

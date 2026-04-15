# Scraper Command Usage

All commands run inside Docker. Commands that use Playwright (browser automation) require
the `scraper` container. Commands that use only HTTP requests can run in the lighter `web`
container.

---

## fetch_jpx_listings

Scrapes the JPX listed-company search service (東証上場会社情報サービス) in two phases.
Requires Playwright — use the `scraper` container.

```
docker compose run --rm scraper python manage.py fetch_jpx_listings [flags]
```

### Phases

**Phase 1 — List collection**
Submits the 簡易検索 form with all market segments (excluding ETF/ETN/REIT/インフラ/その他),
paginates through results 200 at a time, and upserts each company's name, market segment,
industry (33業種), and fiscal month into the DB.

**Phase 2 — Detail pages**
For each company that is new or stale, navigates to its 基本情報 detail page and scrapes:
representative name/title, established date, address, share count, unit shares, fiscal year
end, earnings announcement dates (annual/Q1/Q2/Q3), 信用/貸借 flags, and then switches to
the 適時開示情報 tab to collect disclosure records (PDF, XBRL, HTML links).

Staleness is determined by comparing `detail_scraped_at` against `updated_at`, and
`disclosures_scraped_at` against the `--disclosure-days` cutoff.

### Flags

| Flag | Default | Description |
|---|---|---|
| `--skip-detail` | off | Phase 1 only — collect list data, skip detail pages |
| `--detail-only` | off | Phase 2 only — skip Phase 1, load companies from DB |
| `--codes 7203 6758` | all | Limit Phase 2 to specific stock codes |
| `--industry 3650 3600` | all | Limit Phase 2 to companies in these 33業種 codes |
| `--limit N` | 0 (all) | Stop after N companies |
| `--disclosure-days N` | 7 | Re-scrape disclosures for companies last fetched more than N days ago |
| `--delay N` | 1.5 | Seconds between detail-page requests |
| `--no-headless` | off | Show browser window (starts Xvfb automatically) |
| `--screenshots` | off | Save debug screenshots to `/app/debug/` |

### Common invocations

```bash
# Full run (Phase 1 + Phase 2)
docker compose run --rm scraper python manage.py fetch_jpx_listings

# Phase 1 only — refresh company list without hitting detail pages
docker compose run --rm scraper python manage.py fetch_jpx_listings --skip-detail

# Phase 2 only — refresh details for existing DB records
docker compose run --rm scraper python manage.py fetch_jpx_listings --detail-only

# Retry specific companies
docker compose run --rm scraper python manage.py fetch_jpx_listings --detail-only --codes 7203 6758

# Refresh one industry sector
docker compose run --rm scraper python manage.py fetch_jpx_listings --detail-only --industry 3650

# Quick test — first 5 companies, show browser
docker compose run --rm scraper python manage.py fetch_jpx_listings --limit 5 --no-headless
```

---

## fetch_jpx_prices

Fetches current share price data from the JPX JSON API and updates each company's
share price, yearly high/low (with dates), and market cap (recomputed automatically).
No Playwright required — runs in the `web` container.

```
docker exec -it web python manage.py fetch_jpx_prices [flags]
```

### What it updates

| Field | API field |
|---|---|
| `share_price` | DPP (現在値) |
| `yearly_high` | YHPR (年初来高値) |
| `yearly_high_date` | YHPD |
| `yearly_low` | YLPR (年初来安値) |
| `yearly_low_date` | YLPD |
| `market_cap` | recomputed via `Company.save()` |

Targets all JPX-listed companies (`is_non_jpx=False`) except TOKYO PRO Market (`tse_pro`),
which does not have public price data.

### Flags

| Flag | Default | Description |
|---|---|---|
| `--codes 6758 7203` | all | Only fetch prices for these stock codes |
| `--start-from CODE` | — | Resume from this stock code (inclusive), skipping everything before it |
| `--limit N` | 0 (all) | Stop after N companies |
| `--delay N` | 0.5 | Seconds between API requests |
| `--mark-delisted` | off | Set `status=watchlist` on companies that return no price data (for review) |

### Common invocations

```bash
# Update all companies
docker exec -it web python manage.py fetch_jpx_prices

# Update specific companies
docker exec -it web python manage.py fetch_jpx_prices --codes 6758 7203

# Resume from a specific code after an interrupted run
docker exec -it web python manage.py fetch_jpx_prices --start-from 202A

# Quick test — first 10 companies
docker exec -it web python manage.py fetch_jpx_prices --limit 10

# Flag companies with no price data (possibly delisted) as watchlist for review
docker exec -it web python manage.py fetch_jpx_prices --mark-delisted
```

---

## fetch_shareholders

Fetches major shareholder (大株主) data from EDINET annual securities reports
(有価証券報告書) via the EDINET API. Requires `EDINET_API_KEY` in `.env`.
No Playwright required — runs in the `web` container.

```
docker exec -it web python manage.py fetch_shareholders [flags]
```

### Phases

**Phase 1 — Document index sync**
Scans the EDINET document list API for the last N days (`--days`) and stores entries
in the `EDINETDocument` table. On subsequent runs only new dates are fetched (incremental).
Covers annual reports (有価証券報告書, form 030000), semi-annual reports (040000/040001),
and the new semi-annual format (043A00).

**Phase 2 — Shareholder extraction**
For each company, finds the most recent annual report in the index (falls back to
semi-annual if no annual exists), downloads the XBRL-to-CSV ZIP (type=5), and parses:
- Major shareholders: name, address, shares held, shareholding ratio (%) — ranked 1–10
- Treasury shares (自己株式数) — stored on the Company record
- Period end date — used as the `as_of_date` on each ShareRecord

The entire ShareRecord snapshot for a company is replaced on each successful fetch.

### Flags

| Flag | Default | Description |
|---|---|---|
| `--codes 6758 7203` | all | Only fetch shareholders for these stock codes |
| `--industry 3650 3600` | all | Only fetch shareholders for companies in these 33業種 codes |
| `--days N` | 400 | How many past days to scan for reports |
| `--delay N` | 1.0 | Seconds between document downloads |

### Common invocations

```bash
# Full run
docker exec -it web python manage.py fetch_shareholders

# Specific companies
docker exec -it web python manage.py fetch_shareholders --codes 6758 7203

# One industry sector
docker exec -it web python manage.py fetch_shareholders --industry 3650

# Multiple sectors
docker exec -it web python manage.py fetch_shareholders --industry 3600 3650 3700

# Scan further back (e.g. for companies with late annual report filings)
docker exec -it web python manage.py fetch_shareholders --days 600
```

---

## sync_edinet_index

One-time (or periodic) cache warm-up that scans the EDINET document list API day by day
and populates the `EDINETDocument` table for all companies in the database.
After running this, `fetch_edinet` uses the cache for every company and completes in
seconds rather than minutes per company.

Only stores documents whose EDINET code matches a Company in the database, and only
for the form codes used by `fetch_edinet` and `fetch_shareholders`
(030000, 040000, 040001, 043000, 043001, 043A00).
Already-synced dates are skipped automatically — re-running is safe and fast.

```
docker compose exec web python manage.py sync_edinet_index [flags]
```

### Flags

| Flag | Default | Description |
|---|---|---|
| `--years N` | 5 | Scan this many past calendar years |
| `--days N` | — | Scan this many past days (mutually exclusive with `--years`) |
| `--delay N` | 0.5 | Seconds between API requests |
| `--force` | off | Re-scan dates already in the DB |

### Common invocations

```bash
# Full 5-year sync (run once; takes ~15 minutes)
docker compose exec web python manage.py sync_edinet_index

# Catch up on the past month
docker compose exec web python manage.py sync_edinet_index --days 30

# Re-scan everything from scratch
docker compose exec web python manage.py sync_edinet_index --force
```

---

## fetch_edinet

Fetches full annual (and semi-annual) financial statements from EDINET via the EDINET API v2.
Downloads XBRL-to-CSV packages and parses detailed P&L, B/S, and CF data.
Requires `EDINET_API_KEY` in `.env`. No Playwright required — runs in the `web` container.

```
docker compose exec web python manage.py fetch_edinet [flags]
```

### What it fetches

| Form code | Type | Fields |
|---|---|---|
| 030000 (有価証券報告書) | Annual | Full P&L, B/S (incl. debt components), CF (incl. capex, depreciation), EPS, ROE, BPS |
| 043A00 (半期報告書) | Q2 / semi-annual | Same as annual but covering the first 6 months |

Upserts into `FinancialReport` + `IncomeStatement` + `BalanceSheet` + `CashFlowStatement`
using `(company, fiscal_year, fiscal_quarter)` as the natural key, so it merges with any
TDnet record for the same period.

### Flags

| Flag | Description |
|---|---|
| `--edinet-code E00012` | Single company by EDINET code |
| `--industry-33 0050` | All companies in a 33-industry code |
| `--industry-17 9` | All companies in a 17-industry code |
| `--all` | All companies with an EDINET code |
| `--year 2025` | Fiscal year to fetch (matches `submit_date` year in EDINET cache, or scans that calendar year) |
| `-v 2` | Verbose — print each parsed field and value |

### Notes

- **Speed**: Uses the `EDINETDocument` cache (populated by `fetch_shareholders`) to avoid
  day-by-day API scanning. Run `fetch_shareholders` first for fastest results. If the cache
  is empty for a company/year, the command falls back to scanning weekdays only and caps at
  today's date.
- **Fiscal year convention**: `--year 2025` fetches the annual report for the fiscal year
  ending in 2025 (e.g. March 2025 for a March fiscal year company).

### Common invocations

```bash
# Single company (by EDINET code)
docker compose exec web python manage.py fetch_edinet --edinet-code E00012 --year 2025

# Single company verbose
docker compose exec web python manage.py fetch_edinet --edinet-code E00012 --year 2025 -v 2

# One industry sector
docker compose exec web python manage.py fetch_edinet --industry-33 0050 --year 2025

# All companies
docker compose exec web python manage.py fetch_edinet --all --year 2025
```

---

## fetch_tse

Fetches quarterly and annual financial summaries from TDnet (東証適時開示) XBRL packages
(決算短信). Parses inline XBRL (iXBRL) from the Summary and Attachment files.
No API key required. No Playwright required — runs in the `web` container.

Requires `DisclosureRecord` rows with `xbrl_url` populated — run `fetch_jpx_listings`
first to scrape the disclosure links.

```
docker compose exec web python manage.py fetch_tse [flags]
```

### What it fetches

| Quarter | P&L | B/S summary | B/S detail | CF |
|---|---|---|---|---|
| Q1, Q3 | revenue, OP, ordinary profit, net income, EPS, YoY% | total assets, equity, equity ratio, BPS | current/non-current assets & liabilities, cash, debt components | — |
| Q2 (半期) | same | same | same | operating, investing, financing |
| Annual | same + ROE, operating margin | same | same | operating, investing, financing |

Supports both **J-GAAP** and **IFRS** companies (US-GAAP in progress).
Note: IFRS companies have no `ordinary_profit` equivalent — that field stays null.

Upserts into `FinancialReport` + `IncomeStatement` + `BalanceSheet` + `CashFlowStatement`
using `(company, fiscal_year, fiscal_quarter)` as the natural key, merging with any
EDINET record for the same period.

### Flags

| Flag | Description |
|---|---|
| `--stock-code 1301` | Single company by TSE stock code |
| `--edinet-code E00012` | Single company by EDINET code |
| `--industry-33 0050` | All companies in a 33-industry code |
| `--industry-17 9` | All companies in a 17-industry code |
| `--all` | All companies |
| `--year 2025` | Fiscal year to fetch — matches titles containing `2025年` (e.g. "2025年3月期") |
| `-v 2` | Verbose — print each parsed field and value |

### Notes

- **`--year` meaning**: matches the fiscal year label in the disclosure title. `--year 2026`
  fetches all quarters of the fiscal year ending in 2026 (Q1 through Annual), regardless
  of when the disclosures were filed.
- **EDINET vs TDnet**: TDnet data arrives faster (～45 days after quarter end) but has less
  detail than EDINET annual reports (no capex, depreciation, or individual debt components
  from TDnet). Run both for full coverage.

### Common invocations

```bash
# Single company — current fiscal year (by stock code)
docker compose exec web python manage.py fetch_tse --stock-code 1301 --year 2026

# Single company verbose
docker compose exec web python manage.py fetch_tse --stock-code 1301 --year 2025 -v 2

# One industry sector — two fiscal years
docker compose exec web python manage.py fetch_tse --industry-33 0050 --year 2025
docker compose exec web python manage.py fetch_tse --industry-33 0050 --year 2026

# All companies
docker compose exec web python manage.py fetch_tse --all --year 2026
```

---

## Recommended update schedule

| Command | Frequency | Notes |
|---|---|---|
| `fetch_jpx_listings --skip-detail` | Weekly | Catches new listings and delistings |
| `fetch_jpx_listings --detail-only` | Weekly | Refreshes representative, address, earnings dates, disclosure links |
| `fetch_jpx_prices` | Daily | Share price and market cap |
| `sync_edinet_index` | Monthly | Keep EDINETDocument cache current; run `--days 35` for incremental updates |
| `fetch_shareholders` | Quarterly | After annual report filing season |
| `fetch_tse --all --year YYYY` | Quarterly | After each earnings season; run for current and prior fiscal year |
| `fetch_edinet --all --year YYYY` | Annually | After annual report filing season (June–July for March fiscal year companies) |

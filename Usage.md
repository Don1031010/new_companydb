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

## fetch_nse_listings

Fetches all listed companies from the Nagoya Stock Exchange (名古屋証券取引所) via
its internal JSON API and upserts Company + Listing records.
No Playwright required — runs in the `web` container.

```
docker compose exec web python manage.py fetch_nse_listings [flags]
```

### Phases

**Phase 1 — List collection**
Fetches all プレミア市場, メイン市場, and ネクスト市場 companies (313 as of 2026).
- **Dual-listed (TSE + NSE)** — adds an NSE `Listing` row; patches blank `name_en`,
  `industry_33`, `fiscal_year_end_month`, and `fiscal_year_end_day` fields.
- **NSE-only (~59 companies)** — creates a new `Company` with `is_non_jpx=True`
  and an NSE `Listing` row.

**Phase 2 — Detail scrape (`--detail` flag)**
Calls `/api/stock/view.json` for each NSE-only company (or all NSE companies with
`--all`) and populates: representative name/title, address, established date,
listing date, shares outstanding, margin/lending flags, `fiscal_year_end_day`.
Also backfills recent disclosure records (up to ~10 per company) into
`DisclosureRecord` using `pdf_filename` as the deduplication key — the same
filename used by TDnet and JPX, so records merge cleanly.

NSE market segments map to existing choices: `nse_premier`, `nse_main`, `nse_next`.

### Flags

| Flag | Default | Description |
|---|---|---|
| `--detail` | off | Run Phase 2 after Phase 1 |
| `--detail-only` | off | Skip Phase 1; run Phase 2 only |
| `--all` | off | Phase 2 for all NSE companies, not just NSE-only |
| `--delay N` | 0.5 | Seconds between Phase 2 requests |
| `--dry-run` | off | Parse without writing to DB |
| `--verbose` | off | Show each company as it is processed |

### Common invocations

```bash
# Phase 1 only — sync company list and listings
docker compose exec web python manage.py fetch_nse_listings

# Phase 1 + Phase 2 — full run including detail for NSE-only companies
docker compose exec web python manage.py fetch_nse_listings --detail

# Phase 2 only — refresh detail for NSE-only companies (skip list sync)
docker compose exec web python manage.py fetch_nse_listings --detail-only

# Preview
docker compose exec web python manage.py fetch_nse_listings --dry-run --verbose
```

---

## fetch_sse_listings

Scrapes the Sapporo Stock Exchange (札幌証券取引所) listed-company page and upserts
Company + Listing records. No Playwright required — runs in the `web` container.

```
docker compose exec web python manage.py fetch_sse_listings [flags]
```

### What it scrapes

**Phase 1 — List page** (`/listing/list`)
Collects all 68 companies from `<section id="catXX">` elements:
  - `cat01`–`cat21`, `cat23` → 本則市場 (`sse_main`), with industry (業種) from the section heading
  - `cat22` → アンビシャス市場 (`sse_ambitious`)
  - `cat24` → Sapporo PRO Frontier Market (`sse_frontier`, currently empty)

Companies with `class="tandoku"` on their anchor are 単独上場 (SSE-only, 17 companies)
and are created with `is_non_jpx=True`. Dual-listed companies get an SSE `Listing` row only.

The 北海道ESGプロボンドマーケット (bond market) does not appear on `/listing/list`
and requires no filtering.

**Phase 2 — Detail pages** (`--detail` flag, SSE-only companies by default)
Fetches each company's detail page and extracts `address_ja` and `website`.
(No fiscal year end, listing date, or representative data is available from SSE.)
Use `--all` to run Phase 2 for all 68 companies.

SSE market segments: `sse_main` (本則), `sse_ambitious` (アンビシャス),
`sse_frontier` (Sapporo PRO Frontier Market).

### Flags

| Flag | Default | Description |
|---|---|---|
| `--detail` | off | Phase 2: scrape detail pages for address/website |
| `--all` | off | With `--detail`: scrape all SSE companies, not just SSE-only |
| `--delay N` | 0.5 | Seconds between detail-page requests |
| `--dry-run` | off | Parse without writing to DB |
| `--verbose` | off | Show each company as it is processed |

### Common invocations

```bash
# Phase 1 only — sync company list and listings (~1 second, single HTTP request)
docker compose exec web python manage.py fetch_sse_listings

# Phase 1 + address/website for SSE-only companies
docker compose exec web python manage.py fetch_sse_listings --detail

# Preview
docker compose exec web python manage.py fetch_sse_listings --dry-run --verbose
```

---

## fetch_fse_listings

Scrapes the Fukuoka Stock Exchange (福岡証券取引所) listed-company pages and upserts
Company + Listing records. No Playwright required — runs in the `web` container.

```
docker compose exec web python manage.py fetch_fse_listings [flags]
```

### What it scrapes

**Step 1 — List page** (`/listed/list.php`)
Collects all company entries from three sections: 本則 (96), Q-Board (22), and
Fukuoka PRO Market (16) — 134 companies total. All three sections have detail-page
links (`detail.php?copid=...`); the page is Shift-JIS encoded.

**Step 2 — Detail pages** (`/listed/detail.php?copid=...`)
For every company, fetches the detail page and extracts: stock code, company name,
market section, industry (業種), fiscal year end (決算期 — MMDD or "N月末" format),
establishment date, address, representative title/name, listing date, shares
outstanding, and website URL.

- **Dual-listed companies** — adds an FSE `Listing` row; patches blank detail fields.
- **FSE-only companies** (~32) — creates a new `Company` with `is_non_jpx=True`
  and an FSE `Listing` row.

FSE disclosure filenames are FSE-specific and do not match TDnet/JPX filenames.
Disclosures for FSE-listed companies are populated by `fetch_tdnet_daily` instead.

FSE market segments: `fse_main` (本則), `fse_q_board` (Q-Board),
`fse_pro_market` (Fukuoka PRO Market).

### Flags

| Flag | Default | Description |
|---|---|---|
| `--skip-existing` | off | Skip companies whose stock code is already in the DB |
| `--delay N` | 0.5 | Seconds between detail-page requests |
| `--dry-run` | off | Parse without writing to DB |
| `--verbose` | off | Show each company as it is processed |

### Common invocations

```bash
# Full run — all 134 companies (~70 seconds at 0.5s delay)
docker compose exec web python manage.py fetch_fse_listings

# Preview what would be scraped
docker compose exec web python manage.py fetch_fse_listings --dry-run --verbose

# Re-run, only updating existing records (skip new companies)
docker compose exec web python manage.py fetch_fse_listings --skip-existing
```

---

## fetch_tdnet_daily

Scrapes the TDnet disclosure feed (東証適時開示情報伝達システム) for new disclosure
records and upserts them into `DisclosureRecord`. No Playwright required — runs in
the `web` container.

TDnet publishes same-day disclosures (no delay), making this the primary daily source.
`pdf_url` is set to the temporary TDnet URL (~1 month lifespan); `fetch_jpx_listings`
overwrites it with the permanent JPX URL when it next runs.

```
docker compose exec web python manage.py fetch_tdnet_daily [flags]
```

### What it fetches

Parses `I_list_{page:03d}_{YYYYMMDD}.html` (up to 100 rows per page, paginated
automatically). Each row provides: stock code, title, PDF link, and XBRL zip link
(when available). Only companies already in the DB are saved; ETFs, REITs, and other
non-tracked codes are skipped.

Deduplication key: `(company, pdf_filename)` — the bare PDF filename
(e.g. `140120260416505389.pdf`) is identical between TDnet and JPX, so records
created here merge cleanly with those scraped by `fetch_jpx_listings`.

### Flags

| Flag | Default | Description |
|---|---|---|
| `--days N` | 1 | Fetch the last N days including today |
| `--date YYYY-MM-DD` | today | Fetch a specific date (mutually exclusive with `--days`) |
| `--dry-run` | off | Parse and print without writing to DB |
| `--verbose` | off | Show every row, including skipped (company not in DB) |

### Common invocations

```bash
# Today's disclosures (default)
docker compose exec web python manage.py fetch_tdnet_daily

# Back-fill the past week
docker compose exec web python manage.py fetch_tdnet_daily --days 7

# Specific date
docker compose exec web python manage.py fetch_tdnet_daily --date 2026-04-15

# Preview without saving
docker compose exec web python manage.py fetch_tdnet_daily --dry-run --verbose
```

---

## Recommended update schedule

### Daily

Run every trading day (weekdays), in this order:

| # | Command | Why this order |
|---|---|---|
| 1 | `fetch_tdnet_daily` | Captures same-day disclosures; no dependencies |
| 2 | `fetch_jpx_prices` | Prices and market cap; no dependencies |

```bash
docker compose exec web python manage.py fetch_tdnet_daily
docker compose exec web python manage.py fetch_jpx_prices
```

---

### Weekly

Run once a week (e.g. Sunday night), in this order:

| # | Command | Why this order |
|---|---|---|
| 1 | `fetch_jpx_listings --skip-detail` | Refreshes the master company list first — catches new listings and delistings before anything else reads the DB |
| 2 | `fetch_jpx_listings --detail-only` | Enriches company records and overwrites temporary TDnet `pdf_url`s with permanent JPX URLs; must run after step 1 so new companies are already in the DB |
| 3 | `fetch_jpx_prices` | Catch up on any price gaps from the daily run |

```bash
docker compose exec web python manage.py fetch_jpx_listings --skip-detail
docker compose exec web python manage.py fetch_jpx_listings --detail-only
docker compose exec web python manage.py fetch_jpx_prices
```

---

### Monthly

Run once a month, in this order:

| # | Command | Why this order |
|---|---|---|
| 1 | `fetch_jpx_listings --skip-detail` | Ensure the JPX company list is current before syncing other exchanges |
| 2 | `fetch_nse_listings` | Add/update NSE listings; dual-listed companies must already exist (from JPX) |
| 3 | `fetch_fse_listings` | Add/update FSE listings; same reason |
| 4 | `fetch_sse_listings` | Add/update SSE listings; same reason |
| 5 | `sync_edinet_index --days 35` | Extend the EDINET document cache to cover the past month |

```bash
docker compose exec web python manage.py fetch_jpx_listings --skip-detail
docker compose exec web python manage.py fetch_nse_listings
docker compose exec web python manage.py fetch_fse_listings
docker compose exec web python manage.py fetch_sse_listings
docker compose exec web python manage.py sync_edinet_index --days 35
```

---

### Quarterly (after each earnings season)

Japanese companies report on roughly the following schedule:
- **Q1** results: mid-August  
- **Q2 / half-year** results: mid-November  
- **Q3** results: mid-February  
- **Annual** results: mid-May (for March fiscal year companies)

Run after each wave of filings, in this order:

| # | Command | Why this order |
|---|---|---|
| 1 | `sync_edinet_index --days 90` | Ensure the EDINET cache covers the full reporting window before fetching financials |
| 2 | `fetch_tse --all --year YYYY` | Parses quarterly earnings from TDnet disclosures (fast, ~45 days after quarter end) |
| 3 | `fetch_shareholders` | Parses major shareholders from EDINET annual reports; run after the May annual reporting season |

```bash
docker compose exec web python manage.py sync_edinet_index --days 90
docker compose exec web python manage.py fetch_tse --all --year 2026
docker compose exec web python manage.py fetch_shareholders
```

`fetch_shareholders` only needs to run once a year (after the annual report filing season, typically June–July for March fiscal year companies).

---

### Annually (after annual report filing season, ~July)

| # | Command | Why this order |
|---|---|---|
| 1 | `sync_edinet_index --years 1` | Ensure the full year of EDINET documents is cached |
| 2 | `fetch_edinet --all --year YYYY` | Parses full annual financial statements (P&L, B/S, CF) from EDINET; richer than TDnet but slower |

```bash
docker compose exec web python manage.py sync_edinet_index --years 1
docker compose exec web python manage.py fetch_edinet --all --year 2026
```

---

### Dependency summary

```
fetch_jpx_listings (Phase 1)   ← must run before Phase 2 and before regional exchange scrapers
    └─ fetch_jpx_listings (Phase 2)   ← overwrites TDnet pdf_url with permanent JPX URLs
    └─ fetch_nse_listings / fetch_fse_listings / fetch_sse_listings
           └─ fetch_tdnet_daily   ← works on any company already in DB (no ordering constraint)

sync_edinet_index   ← must run before fetch_tse, fetch_shareholders, fetch_edinet
    └─ fetch_tse
    └─ fetch_shareholders
    └─ fetch_edinet

fetch_jpx_prices   ← no dependencies; can run any time after companies exist
```

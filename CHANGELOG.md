# Changelog

## 2026-04-13

### New model: `DisclosureRecord` (`listings/models.py`, migrations `0015`–`0018`)

- Stores 適時開示情報 entries scraped from the JPX company detail page
- Fields: `company` (FK), `disclosed_date`, `title`, `pdf_url`, `xbrl_url`, `html_summary_url`, `html_attachment_url`, `scraped_at`
- Both `・[決算情報]` (id=`1101_N`) and `・[決定事実 / 発生事実]` (id=`1102_N`) rows are captured in a single flat table, deduplicated by `(company, pdf_url)`
- 1101 rows are processed first; when the same document (e.g. 決算短信) appears in both tables, the 1101 version wins because it carries richer data (HTML summary and attachment links)
- 1102-only entries (M&A, buybacks, stock splits, etc.) are also stored
- Added `disclosures_scraped_at` to `Company` to track when disclosures were last fetched independently of `detail_scraped_at`

### `fetch_jpx_listings` — 適時開示情報 scraping

- Added `_scrape_disclosures(page)`: after scraping 基本情報, calls `changeTab('2')` on the same page and parses all `1101_*` and `1102_*` rows; includes hidden (`display:none`) rows since Playwright sees the full DOM
- Added `_save_disclosures(code4, disclosures)`: uses `get_or_create` keyed on `(company, pdf_url)` so re-runs are safe; stamps `company.disclosures_scraped_at` after each company
- Added `--industry` argument: filter Phase 2 by 33-industry code (same as `fetch_shareholders`)
- Added `--disclosure-days` argument (default 7): a company is included in Phase 2 if its basic info is stale **or** if `disclosures_scraped_at` is older than N days — so newly published disclosures are picked up on regular runs even when 基本情報 has not changed

### Wagtail admin — 適時開示 list (`listings/snippets.py`)

- Added `DisclosureRecordViewSet` to the 上場会社情報 group
- List columns: 会社, 開示日, 表題, 資料
- "資料" column renders compact clickable `PDF · XBRL · HTML · 添付` links using a custom `ResourceLinksColumn` (subclasses Wagtail 7's `Column`, overrides `get_value` to return a `mark_safe` string)
- Sorted by company code then disclosed date descending
- Search by title, stock code, or company name; filter by date
- Detail panels show all URL fields read-only under a "資料リンク" section

### Migrations

- `0015_add_disclosure_record` — `DisclosureRecord` model
- `0016_disclosurerecord_unique_category` — interim: added `category` field with `(company, category, pdf_url)` unique constraint (superseded by 0017)
- `0017_disclosurerecord_remove_category` — removed `category` field, reverted unique constraint to `(company, pdf_url)`
- `0018_company_disclosures_scraped_at` — `disclosures_scraped_at` field on Company

---

## 2026-04-10 (session 2)

### `fetch_shareholders` — EDINETDocument cache (`listings/models.py`, migration `0014`)

- Added `EDINETDocument` model to cache EDINET document list entries in the DB:
  - Fields: `doc_id` (unique), `edinet_code`, `ordinance_code`, `form_code`, `period_end`, `submit_date`, `description`, `withdrawn`
- Phase 1 now calls `_sync_edinet_docs()` instead of scanning all 400 days every run:
  - Checks the latest `submit_date` already in `EDINETDocument`; only scans dates from `latest - 1 day` forward (or 400 days back if table is empty)
  - The one-day overlap catches documents added to EDINET after the previous run
  - `bulk_create(..., ignore_conflicts=True)` prevents duplicates
- `_build_index_from_db()` builds `{edinet_code: {docID, period_end}}` from the cached table instead of from an in-memory scan
- Bug fixes during sync:
  - Documents with null `edinetCode` are skipped (non-company filings)
  - `ordinanceCode`, `formCode`, `docDescription` fields guarded with `or ""` to handle JSON nulls

### `fetch_shareholders` — period end date from CSV

- Added `ELEM_PERIOD_END = "jpdei_cor:CurrentPeriodEndDateDEI"` element parsing in `_parse_csv()`
- `_parse_csv()` now returns a third value: `period_end` extracted directly from the XBRL CSV
- `ShareRecord.as_of_date` is set from the CSV-parsed date (falls back to `entry["period_end"]` from the document list API)
- Fixes semi-annual reports where the API's `periodEnd` may reflect the fiscal year end (`2026-03-31`) rather than the actual interim period end (`2025-09-30`)

## 2026-04-10 (session 1)

### Company model (`listings/models.py`)

- Added share price fields:
  - `share_price` — 株価（円）, `DecimalField`
  - `yearly_high` / `yearly_high_date` — 年初来高値 and date
  - `yearly_low` / `yearly_low_date` — 年初来安値 and date
- `market_cap` is now auto-computed in `Company.save()` as `shares_outstanding × share_price / 1_000_000` instead of being set manually
- Added `edinet_code` — EDINETコード (e.g. `E02167`), populated by `fetch_edinet_codes`
- Added `treasury_shares` — 自己株式数, fetched from EDINET annual reports

### Shareholder models (`listings/models.py`)

- Added `Institution` model — parent financial institution (name, name_en, name_zh); allows grouping shareholder accounts that belong to the same bank
- Added `Shareholder` model — individual named shareholder account (name, address, optional FK to Institution)
- Added `ShareRecord` model — current-snapshot holding of one shareholder in one company (rank, shares, percentage, as_of_date); uses `ParentalKey` for Wagtail InlinePanel support
- Note: `percentage` stores the EDINET-reported ratio which **excludes treasury shares** from the denominator (`発行済株式（自己株式を除く。）の総数に対する所有株式数の割合`)

### Wagtail admin (`listings/snippets.py`)

- Added `InstitutionViewSet` — searchable by name/name_en/name_zh, filterable
- Added `ShareholderViewSet` — searchable, filterable by institution
- Added `InlinePanel("share_records")` to Company edit page under 大株主情報 section
- All four models grouped under the existing 上場会社情報 menu

### `fetch_jpx_listings` (`listings/management/commands/fetch_jpx_listings.py`)

- Added `--codes` argument — re-scrape details for specific stock codes only (e.g. `--codes 5619 7723 9404`), useful for retrying individual failures without reprocessing all stale companies

### New command: `fetch_jpx_prices` (`listings/management/commands/fetch_jpx_prices.py`)

- Fetches `share_price`, `yearly_high`, `yearly_high_date`, `yearly_low`, `yearly_low_date` from the JPX JSON API (`quote.jpx.co.jp/jpxhp/jcgi/wrap/qjsonp.aspx`)
- Auto-recomputes `market_cap` via `Company.save()` after each update
- Excludes TSE Pro Market companies (`tse_pro`)
- Supports `--codes`, `--limit`, `--delay`; runs in the `web` container (no Playwright needed)

### New command: `fetch_edinet_codes` (`listings/management/commands/fetch_edinet_codes.py`)

- Downloads the public EDINET code list ZIP (`Edinetcode.zip`, no API key required)
- Maps 5-digit 証券コード → EDINETコード and populates `Company.edinet_code`

### New command: `fetch_shareholders` (`listings/management/commands/fetch_shareholders.py`)

- Requires `EDINET_API_KEY` in `.env`
- Phase 1: scans the last N days (default 400) of EDINET document submissions to build an index of the most recent `有価証券報告書` or `半期報告書` per company
- Phase 2: downloads the XBRL-to-CSV ZIP (type=5) for each company, parses `NameMajorShareholders`, `AddressMajorShareholders`, `NumberOfSharesHeld`, `ShareholdingRatio`, and `TotalNumberOfSharesHeldTreasurySharesEtc`
- Replaces the current ShareRecord snapshot and updates `Company.treasury_shares`
- Supports `--codes`, `--days`, `--delay`

### Dependencies (`requirements.txt`)

- Added `requests>=2.32`
- Added `beautifulsoup4>=4.12`

### Migrations

- `0006_add_share_price` — `share_price` field
- `0007_add_yearly_high_low` — `yearly_high`, `yearly_high_date`, `yearly_low`, `yearly_low_date`
- `0008_add_shareholder_sharerecord` — `Shareholder`, `ShareRecord` models
- `0009_sharerecord_parentalkey` — changed `ShareRecord.company` to `ParentalKey`
- `0010_add_edinet_code` — `edinet_code` field on Company
- `0011_add_treasury_shares` — `treasury_shares` field on Company
- `0012_add_institution` — `Institution` model, `institution` FK on Shareholder
- `0013_add_institution_name_zh` — `name_zh` field on Institution

---

## 2026-04-08 / 2026-04-09

### Company model (`listings/models.py`)

- Added 4 earnings announcement date fields:
  - `earnings_date_annual` — 決算発表（予定）
  - `earnings_date_q1` — 第一四半期（予定）
  - `earnings_date_q2` — 第二四半期（予定）
  - `earnings_date_q3` — 第三四半期（予定）
- Renamed `is_single_listed` → `is_non_jpx` (`default=True`, verbose_name `東証非上場`)
- Added `detail_scraped_at` (`DateTimeField`, nullable) to track when Phase 2 detail scraping last ran per company

### Wagtail snippets (`listings/snippets.py`)

- Updated `list_display` and `list_filter` to reflect `is_single_listed` → `is_non_jpx` rename

### Scraper (`listings/management/commands/fetch_jpx_listings.py`)

#### Bug fixes
- **Phase 1 — 151 rows instead of 200**: `_extract_result_rows` was filtering with `code5.isdigit()`, which excluded alphanumeric codes like `130A0`, `131A0` etc. (49 entries per page). Fixed by changing the guard to `len(code5) != 5`.
- **Page 2 — DOM context destroyed**: `_click_next_page` was calling `wait_for_load_state("networkidle")` after a JavaScript-triggered navigation, which could resolve before the navigation actually started. Fixed by replacing with `page.expect_navigation()` as a context manager, which registers the navigation listener before the click.
- **`wait_for_selector` timeout on hidden inputs**: Added `state="attached"` to the post-navigation selector wait — hidden inputs are never "visible" so the default state timed out every time.
- **`DJANGO_ALLOW_ASYNC_UNSAFE`**: Set at the start of `handle()` so Playwright's sync event loop does not block Django ORM calls.
- **Screenshot directory**: Changed from `/app/debug` (permission denied) to `/tmp/debug`.

#### New features
- **Total count verification**: `_extract_total_count` reads the expected total from the paginator text (`／3928件中`) after Phase 1 submits the search. At the end of pagination, logs a warning if the collected count does not match.
- **`--detail-only` flag**: Skips Phase 1 entirely and loads the company list from the database (`is_non_jpx=False`) instead of scraping the JPX list pages. Allows Phase 2 to be run independently.
- **Phase 2 skip already up-to-date companies**: Before scraping details, filters to only companies where `detail_scraped_at` is null or `detail_scraped_at < updated_at` (i.e. the list data has been refreshed since the last detail scrape). Logs how many companies are skipped.
- **`detail_scraped_at` stamping**: `_save_detail` now sets `company.detail_scraped_at = timezone.now()` on every successful detail save.
- **Earnings date scraping**: `_parse_kihon_joho` extracts the 4 earnings date fields from the 基本情報 detail page. `_save_detail` parses and saves them to the model.
- **`is_non_jpx = False`**: `_save_list_data` sets this on every company found during Phase 1, marking it as confirmed listed on JPX.

#### Typical workflow
```bash
# Refresh the company list (Phase 1 only)
docker compose run --rm scraper python manage.py fetch_jpx_listings --skip-detail

# Scrape / resume details (Phase 2 only, skips up-to-date companies)
docker compose run --rm scraper python manage.py fetch_jpx_listings --detail-only

# Full run
docker compose run --rm scraper python manage.py fetch_jpx_listings
```

### Docker / infrastructure

- `Dockerfile`: pinned `wagtail` user UID to `1002` to match the host user, preventing volume permission errors when creating migrations and static files.
- Dropped and recreated `mysite_static_volume` after the UID change to clear files written by the old UID 1000 user (which caused `collectstatic --clear` to fail with `PermissionError`).

### Migrations

- `0004_*` — earnings date fields + `is_non_jpx` rename
- `0005_company_detail_scraped_at` — `detail_scraped_at` field

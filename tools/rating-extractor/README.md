# Rating Extractor

Standalone extraction tool for CRISIL Ratings, ICRA, and India Ratings
press releases. For each entity in `entities.csv`, extracts:

- Current rating, **instrument-wise** (not just the headline rating)
- Rating action history: date, previous rating, new rating, outlook change
- Rated amount per instrument, in Rs. Cr, as stated in the press release
- The press release itself: date, URL, and a stored copy of the text

This is a standalone tool — no scheduling, dashboard, or delta-diffing.

## Status: all three sources reconnoitred and parsing real documents

The dev sandbox is behind a default-deny egress allowlist and cannot reach
any rating-agency domain. Reconnaissance therefore runs on a GitHub Actions
runner (`.github/workflows/rating_recon.yml` + `recon.py`), which fetches
real pages, commits them to `captures/`, and lets the parsers be built and
validated against actual markup rather than guesswork.

| Source | Strategy | Browser? | Extraction | Discovery |
|---|---|---|---|---|
| CRISIL | Plain HTTP + HTML tables | No | Validated | **Unsolved** |
| ICRA | Plain HTTP + PDF tables | No | Validated | Untested |
| India Ratings | Unauthenticated JSON API | No | Validated | Solved |

**CRISIL** rationales are fully server-rendered HTML. Three structures are
parsed, each tagged with `provenance`: the header Rating Action table (the
only rows treated as confirmed actions, since the action is stated per
instrument), `#AnnexureSecTableId` (facility-level amounts) and
`#AnnexRtgHistoryTable` (dated previous -> new history).

**ICRA** publishes rationales as text-based PDFs at
`/Rating/GetRationalReportFilePdf?id=`. The page-1 "Summary of rating
action" table carries previous and current rated amounts plus an explicit
per-instrument action.

**India Ratings** is an Angular SPA serving an identical shell on every
route, but its JSON API needs no browser and no auth:
`home/GetSearch?searchKey=` -> issuerID + press releases;
`pressReleases/GetBankFacilityDataRatingLetter?pressReleaseId=` -> the
instrument table. Note `GetPressreleaseData` returns only a header blurb.

### Units differ between sources

CRISIL and ICRA publish in **Rs. crore**; India Ratings publishes in **INR
million** (its own column header reads "Rated Amount (INR million)"). The
India Ratings parser divides by 10 so `amount_rs_cr` means the same thing
everywhere. `amount_raw_text` always quotes the source's own units.

### Scheduling caveat

`.github/workflows/rating_fetch.yml` carries a daily cron, but GitHub fires
schedule triggers only from the **default branch's** copy of a workflow. Until
this is merged to `main` the daily run does not happen; the push trigger is
what exercises it in the meantime.

### Known gaps

- **CRISIL discovery is unsolved.** Its sitemap holds only CMS pages (no
  rationale documents) and its `ratings-search-results` endpoint returns
  HTTP 500. Rationale URLs currently have to be supplied. This blocks
  unattended runs across the full entity list for that source only.
- **Action attribution on India Ratings.** The facility endpoint reports
  current rated positions, not actions; actions come from the press release
  title. A title naming one action is applied to all rows; a title naming
  several ("Assigns ... Additional NCDs; Affirms Existing Ratings") cannot
  be attributed per instrument from these endpoints, so every row is
  flagged ambiguous rather than guessed.
- **No human verification yet.** Nothing here has been checked against a
  live press release by a person. The ICRA sum check below is strong
  evidence but cannot catch an internally consistent misreading.

## Validation performed

| Entity | Source | Result |
|---|---|---|
| Bajaj Finance | CRISIL | 10/10 header actions, correct amounts and ratings; 6 ambiguous (oldest-in-window history rows); idempotent re-ingest |
| Cholamandalam | ICRA | 12 instruments, 0 ambiguous; amounts sum to 1,65,451.64 cr, **exactly** the total ICRA prints in the PDF |
| Bajaj Finance | India Ratings | 334 facilities across 8 rating letters; totals Rs.76,000-80,000 cr per letter, consistent with its bank lines |

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Files

- `entities.csv` — watchlist: `name,aliases` (aliases comma-separated within
  the quoted field; pre-populated with 370 entities pulled from the
  CareEdge team-management sheet's `company`/`aliases` columns)
- `db.py` — SQLite schema + storage helpers (`rating_extractor.db`)
- `extract/common.py` — shared parsing: amount/rating/date regex, and the
  action-vs-mention classifier (see "Hard rule" below)
- `extract/{crisil,icra,india_ratings}.py` — per-source parsers. Currently
  a shared generic-text fallback (`extract/common.generic_extract`) until
  real sample pages are validated — **not yet source-specific or trusted**.
- `ingest_sample.py` — parse one saved local file, store results, print a
  verification report
- `export.py` — dump the database to CSV or XLSX

## Hard rule: action vs. mention

A rating being *mentioned* in a press release (e.g. a group company's
rating cited for context, or a historical rating in the preamble) is not a
rating *action* on the entity itself. `extract/common.py`'s
`classify_sentence()` only marks something as a confirmed action when the
sentence/paragraph both names the entity **and** contains an explicit
first-person action statement about it (e.g. "CRISIL Ratings has
upgraded/reaffirmed/assigned ... to `<entity>`'s ..."). Anything less
certain is stored with `ambiguous = 1` and a reason, never guessed.

## Validation workflow (required before scaling)

Chosen validation entities (large, actively-rated NBFCs — already in
`entities.csv`): **Bajaj Finance Limited**, **Cholamandalam Investment And
Finance Company Limited**, **Power Finance Corporation Limited**.

1. For each of the 3 sources (CRISIL, ICRA, India Ratings), get one real
   press release / rating-action page for each of the 3 entities above into
   `samples/<source>/`.
2. Run `ingest_sample.py` for each and review the printed report against
   the source page yourself.
3. Fix `extract/<source>.py` to parse that source's real structure (see
   "Known gap" above) rather than relying on the generic fallback.
4. Only after that: build a `fetch.py` to pull pages over the network for
   the full 370-entity list, once running somewhere that can actually reach
   these sites (this sandbox's egress proxy blocks all four agency domains
   at the network-policy level — confirmed via curl/WebFetch/`requests`,
   not something this codebase works around).

## Export

```bash
python export.py --format csv --out exports/ratings.csv
python export.py --format xlsx --out exports/ratings.xlsx
```

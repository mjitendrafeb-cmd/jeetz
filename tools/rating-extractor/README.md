# Rating Extractor

Standalone extraction tool for CRISIL Ratings, ICRA, and India Ratings
press releases. For each entity in `entities.csv`, extracts:

- Current rating, **instrument-wise** (not just the headline rating)
- Rating action history: date, previous rating, new rating, outlook change
- Rated amount per instrument, in Rs. Cr, as stated in the press release
- The press release itself: date, URL, and a stored copy of the text

This is a standalone tool — no scheduling, dashboard, or delta-diffing.

## Status: reconnaissance blocked in this environment

The sandbox this was built in cannot reach `crisilratings.com`, `icra.in`,
or `indiaratings.co.in` — the network egress proxy denies the connection at
the policy level, for every tool (curl, Python `requests`, browser). So the
site-specific parsers in `extract/` have **not** been validated against real
markup yet.

To unblock: save a real page (View Source / Ctrl+U, or a raw API response
from the browser's Network tab) to `samples/<source>/<entity>.html` (or
`.json`), then run:

```bash
python ingest_sample.py --source CRISIL --entity "Bajaj Finance Limited" \
    --url "https://..." --file samples/CRISIL/bajaj_finance.html
```

(`--source` must be exactly `CRISIL`, `ICRA`, or `"India Ratings"`.) This
runs extraction against the saved file and prints every extracted field
next to the source snippet it came from, so you can verify amount / rating
/ date before anything is trusted. Nothing is fetched over the network by
this command — it's pure local parsing, for building and validating
selectors. See `samples/example/synthetic_crisil_sample.html` for a
made-up (not real) page you can run this against right now as a smoke test:

```bash
python ingest_sample.py --source CRISIL --entity "Bajaj Finance Limited" \
    --url "https://example.invalid/smoketest" \
    --file samples/example/synthetic_crisil_sample.html
```

**Known gap found by that smoke test**: the current generic parser only
classifies a text unit (roughly one sentence) if it repeats the entity's
name. Real rationale pages typically name the entity once and then list
multiple instruments/ratings afterward without repeating it — those would
be missed. Once you get a real sample, the per-source parser should key
off that page's actual instrument table/structure instead of sentence-level
name-matching.

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

# CRA Rating Tracker

Tracks rating actions from **CRISIL, ICRA, CARE, and India Ratings** for a
watchlist of companies, keeping a history of each action's rating, outlook,
instrument, and amount rated. Runs as a local Flask dashboard.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000.

## Usage

- **Add a company** from the dashboard: name plus optional comma-separated
  aliases (short names / former names the agencies might use).
- **Refresh all agencies** scrapes CRISIL, ICRA, CARE, and India Ratings'
  public rating-action listing pages for every watchlist company and stores
  any new matches.
- Click a company to see its full rating history (date, agency, instrument,
  amount rated, rating, outlook, action type, and a link to the source).
- You can also run the scrape from the command line without the dashboard:

  ```bash
  python fetch.py                          # all companies
  python fetch.py --company "Some Company" # one company
  ```

## How it works

- `watchlist.json` seeds the initial list on first run (edit it before first
  launch, or manage companies from the dashboard afterwards — both write to
  the same SQLite database, `ratings.db`).
- `scrapers/` has one module per agency. Each fetches that agency's public
  listing page, keeps entries mentioning a watchlist company, and pulls out
  rating, outlook, instrument, and amount via regex from the surrounding
  text.
- `db.py` stores everything in SQLite (`ratings.db`, created on first run).
  Duplicate entries (same company + agency + source link) are skipped.

## Limitations

Agency websites only publish a headline + link on their public listing
pages — full instrument-by-instrument amount and rating detail generally
lives in the linked rating rationale PDF, which isn't parsed here. So:

- `rating` / `amount_text` / `instrument` are filled in only when the
  listing text itself contains enough detail (regex-based, best effort) —
  otherwise they're left blank, but the record (with its source link) is
  still saved so nothing is silently dropped. Follow the link for the full
  rationale.
- These sites redesign their public pages periodically. If a scraper in
  `scrapers/` starts returning nothing, open the listing page in a browser
  and adjust that module's selectors.
- Only the first/default listing page is scraped (no pagination), so very
  old actions won't surface — the tracker is meant to be run regularly
  (e.g. daily via cron) to build up history over time, not to backfill it.

from . import crisil, icra, care, india_ratings

AGENCIES = {
    "CRISIL": crisil.scrape,
    "ICRA": icra.scrape,
    "CARE": care.scrape,
    "India Ratings": india_ratings.scrape,
}

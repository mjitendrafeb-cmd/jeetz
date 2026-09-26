from . import crisil, icra, india_ratings

PARSERS = {
    "CRISIL": crisil.parse,
    "ICRA": icra.parse,
    "India Ratings": india_ratings.parse,
}

IG_RATINGS = {
    "AAA", "AA+", "AA", "AA-",
    "A+", "A", "A-",
    "BBB+", "BBB", "BBB-"
}


def is_below_ig(rating: str) -> bool:
    """
    Return True if current rating is below investment grade.
    Empty / missing ratings are treated as not below IG.
    """
    r = (rating or "").strip()
    if not r or r.lower() in {"na", "n/a", "none"}:
        return False
    return r not in IG_RATINGS
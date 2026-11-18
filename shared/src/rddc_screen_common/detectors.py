"""Pattern detectors for direct identifiers in string values (US formats).

Each detector is a name and a regular expression. They find identifiers with a fixed
shape (Safe Harbor D to O); names and places in prose need the text de-identification
step, not these. UK formats (NHS numbers, postcodes) are not covered yet (inventory,
gap 11).
"""

import re

DETECTORS = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<![\d-])(?:\+?1[-. ])?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?![\d-])"),
    "url": re.compile(r"\b(?:https?|ftp)://([^\s\"'<>]+)", re.IGNORECASE),
    "ipv4": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
    "mrn_label": re.compile(r"\b(?:MRN|medical record (?:number|no\.?))\s*[:#]?\s*[A-Za-z0-9-]{4,}", re.IGNORECASE),
}

FULL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def scan(text, url_hosts=()):
    """Names of the detectors that match the text. A URL counts only if its host (and
    path) does not start with one of url_hosts."""
    hits = []
    for name, rx in DETECTORS.items():
        if name == "url":
            if any(not m.group(1).lower().startswith(tuple(h.lower() for h in url_hosts))
                   for m in rx.finditer(text)):
                hits.append(name)
        elif rx.search(text):
            hits.append(name)
    return hits


def is_full_date(text):
    return bool(FULL_DATE.match(text))

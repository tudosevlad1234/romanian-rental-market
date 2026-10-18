from __future__ import annotations

import re
import unicodedata

WORD_NUMBERS = {
    "o": 1, "una": 1, "un": 1, "doua": 2, "două": 2, "trei": 3, "patru": 4,
    "cinci": 5, "sase": 6, "șase": 6, "sapte": 7, "șapte": 7, "opt": 8,
}  # fmt: skip

EUR_TOKEN = r"(?:€|eur\b|euro\b)"
RON_TOKEN = r"(?:lei\b|leu\b|ron\b)"


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def flat(text: str | None) -> str:
    if not text:
        return ""
    cleaned = strip_diacritics(str(text)).lower().replace("\xa0", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_number(text: str | float | int | None) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = re.search(r"\d[\d.,\s\xa0]*", str(text))
    if not match:
        return None
    raw = re.sub(r"[\s\xa0]", "", match.group(0)).rstrip(".,")
    if not raw:
        return None
    if "." in raw and "," in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        raw = raw.replace(thousands, "").replace(decimal, ".")
    elif "." in raw or "," in raw:
        separator = "." if "." in raw else ","
        head, _, tail = raw.rpartition(separator)
        many = raw.count(separator) > 1
        if many or (len(tail) == 3 and 1 <= len(head) <= 3):
            raw = raw.replace(separator, "")
        else:
            raw = head.replace(separator, "") + "." + tail
    try:
        return float(raw)
    except ValueError:
        return None


def detect_currency(text: str | None) -> str | None:
    cleaned = flat(text)
    if re.search(EUR_TOKEN, cleaned):
        return "EUR"
    if re.search(RON_TOKEN, cleaned):
        return "RON"
    return None


def parse_price(text: str | None, assume: str | None = None) -> tuple[float | None, str | None]:
    amount = parse_number(text)
    if amount is None:
        return None, None
    return amount, detect_currency(text) or assume


def extract_rooms(text: str | None) -> int | None:
    cleaned = flat(text)
    if not cleaned:
        return None
    digits = re.search(r"\b(\d{1,2})\s*(?:camer\w*|cam\b|cam\.)", cleaned)
    if digits:
        return int(digits.group(1))
    words = re.search(r"\b(o|una|un|doua|trei|patru|cinci|sase|sapte|opt)\s+camer\w*", cleaned)
    if words:
        return WORD_NUMBERS[words.group(1)]
    if re.search(r"\bgarsonier\w*|\bstudio\b", cleaned):
        return 1
    return None


def extract_surface(text: str | None) -> float | None:
    cleaned = flat(text)
    patterns = (
        r"(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:mp\b|m2\b|m²|metri\s*patrati|m\s*p\b)",
        r"suprafata\w*\s*(?:utila|construita)?\s*[:\-]?\s*(\d{1,3}(?:[.,]\d{1,2})?)",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return parse_number(match.group(1))
    return None


def floor_info(text: str | None) -> tuple[int | None, int | None]:
    cleaned = flat(text)
    if not cleaned:
        return None, None
    total = None
    pair = re.search(r"\betaj\w*\s*(-?\d{1,2})\s*(?:/|din)\s*(\d{1,2})\b", cleaned)
    if pair:
        return int(pair.group(1)), int(pair.group(2))
    parter_pair = re.search(r"\bparter\w*\s*(?:/|din)\s*(\d{1,2})\b", cleaned)
    if parter_pair:
        return 0, int(parter_pair.group(1))
    if re.search(r"\bdemisol\b", cleaned):
        return -1, total
    if re.search(r"\bsubsol\b", cleaned):
        return -2, total
    if re.search(r"\bparter\b", cleaned):
        return 0, total
    single = re.search(r"\betaj\w*\s*[:\-]?\s*(\d{1,2})\b", cleaned)
    if single:
        return int(single.group(1)), total
    bare = re.match(r"^\s*(-?\d{1,2})\s*(?:/|din)\s*(\d{1,2})\s*$", cleaned)
    if bare:
        return int(bare.group(1)), int(bare.group(2))
    only = re.match(r"^\s*(-?\d{1,2})\s*$", cleaned)
    if only:
        return int(only.group(1)), total
    return None, total


def extract_year(text: str | None) -> int | None:
    match = re.search(r"\b(19[0-9]{2}|20[0-3][0-9])\b", flat(text))
    return int(match.group(1)) if match else None


def listing_id_from_url(url: str) -> str:
    code = re.search(r"\b([0-9a-f]{32})\b", url)
    if code:
        return code.group(1)
    path = url.split("?")[0].rstrip("/")
    last = path.rsplit("/", 1)[-1]
    return re.sub(r"\.html?$", "", last)

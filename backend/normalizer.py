"""Voice/text → catalogue product.

Takes what the shopkeeper said ("oats wala doodh ek litre nahi hai", "मैगी मसाला दो",
"ಗ್ರೀಕ್ ಮೊಸರು ಇಲ್ಲ") and returns the best matching product, quantity and confidence.

Rule-based + fuzzy matching so it runs offline with no API key. In production this is
where an LLM / embedding model plugs in (see `llm_hook`).
"""
import re
import unicodedata

from rapidfuzz import fuzz

# words that carry no product meaning ("not available", "give", "want", units...)
FILLER = {
    # English
    "not", "available", "no", "have", "dont", "don't", "we", "the", "a", "an", "of", "please", "want", "wants",
    "customer", "asked", "for", "some", "one", "packet", "packets", "pack", "piece", "pieces", "bottle",
    "litre", "liter", "litres", "liters", "ltr", "l", "kg", "kilo", "gram", "grams", "g", "ml", "x",
    # Hinglish
    "nahi", "nahin", "hai", "he", "chahiye", "chaiye", "dena", "de", "do", "wala", "waala", "wali", "bhaiya",
    "ek", "kilo", "packet", "stock", "khatam",
    # Hindi (Devanagari)
    "नहीं", "है", "चाहिए", "दो", "दे", "एक", "लीटर", "किलो", "पैकेट", "वाला", "वाली", "भैया", "खत्म",
    # Kannada / Kanglish
    "illa", "beku", "kodi", "kodu", "ondu", "ಇಲ್ಲ", "ಬೇಕು", "ಕೊಡಿ", "ಒಂದು", "ಲೀಟರ್", "ಕೆಜಿ", "ಪ್ಯಾಕೆಟ್",
}

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5,
    "ondu": 1, "eradu": 2, "mooru": 3, "naalku": 4, "aidu": 5,
    "ಒಂದು": 1, "ಎರಡು": 2, "ಮೂರು": 3, "ನಾಲ್ಕು": 4, "ಐದು": 5,
}
# "do" is also Hindi for "give"; only treat it as 2 when followed by a unit/product.
AMBIGUOUS_NUM = {"do", "दो"}

MIN_SCORE = 62


def _clean(text):
    text = unicodedata.normalize("NFC", text.lower())
    # drop punctuation/symbols but keep Indic vowel signs (category M*), which \w misses
    text = "".join(" " if unicodedata.category(ch)[0] in "PSZ" else ch for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def extract_qty(tokens):
    for i, t in enumerate(tokens):
        if t.isdigit() and 0 < int(t) < 100:
            return int(t)
        if t in NUMBER_WORDS:
            if t in AMBIGUOUS_NUM and i == len(tokens) - 1:
                continue  # "... do" at the end = "give", not "two"
            return NUMBER_WORDS[t]
    return 1


def _score(text, alias):
    if f" {alias} " in f" {text} ":
        return 100 + len(alias)  # exact phrase; longer (more specific) alias wins
    return max(fuzz.token_set_ratio(text, alias), fuzz.partial_ratio(alias, text) - 5 if len(alias) > 4 else 0)


def normalize(text, products):
    """products: list of dicts with id, name, aliases(list). Returns dict."""
    cleaned = _clean(text)
    tokens = cleaned.split()
    qty = extract_qty(tokens)
    core = " ".join(t for t in tokens if t not in FILLER and not t.isdigit() and t not in NUMBER_WORDS)
    if not core:
        return {"product_id": None, "qty": qty, "confidence": 0.0, "query": cleaned, "candidates": []}
    scored = []
    for p in products:
        best = max(_score(core, a) for a in p["aliases"] + [p["name"].lower()])
        scored.append((best, p))
    scored.sort(key=lambda x: -x[0])
    top = scored[0]
    cands = [{"product_id": p["id"], "name": p["name"], "score": round(min(s, 100) / 100, 2)} for s, p in scored[:4] if s >= 70][:3]
    if top[0] < MIN_SCORE:
        return {"product_id": None, "qty": qty, "confidence": round(top[0] / 100, 2), "query": core, "candidates": cands}
    return {"product_id": top[1]["id"], "name": top[1]["name"], "qty": qty,
            "confidence": round(min(top[0], 100) / 100, 2), "query": core, "candidates": cands}


def llm_hook(text):  # pragma: no cover - placeholder for production
    """Production: send `text` + top-k embedding matches to an LLM for disambiguation."""
    raise NotImplementedError

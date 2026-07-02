"""Parse Indian-system amounts written in words (lakh / crore aware)."""
import re

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
SCALES = {
    "hundred": 100,
    "thousand": 1000,
    "lakh": 100000, "lakhs": 100000, "lac": 100000, "lacs": 100000,
    "crore": 10000000, "crores": 10000000,
}
NOISE = {"and", "only", "rupees", "rupee", "indian", "rs", "inr", "of", "paise", "paisa"}


def words_to_number(text):
    """Return int value of an amount in words, or None if unparseable."""
    if not text:
        return None
    cleaned = re.sub(r"[^a-z\s]", " ", text.lower().replace("-", " "))
    words = [w for w in cleaned.split() if w and w not in NOISE]
    if not words:
        return None

    total, current = 0, 0
    recognised = 0
    for w in words:
        if w in UNITS:
            current += UNITS[w]
            recognised += 1
        elif w in TENS:
            current += TENS[w]
            recognised += 1
        elif w == "hundred":
            current = max(current, 1) * 100
            recognised += 1
        elif w in SCALES and w != "hundred":
            total += max(current, 1) * SCALES[w]
            current = 0
            recognised += 1
        # unknown word (OCR noise) -> skip silently
    if recognised == 0:
        return None
    return total + current

"""Deterministic name normalisation. Python standard library only.

NFKC, casefold, strip diacritics, then a fixed transliteration of Cyrillic,
Greek and Arabic. CJK is kept as written and never romanised. A match here
may confirm a person or stop a name clearance. It must not be used to invent
a clearance.
"""

from __future__ import annotations

import re
import unicodedata

# Lowercase letters only. Callers casefold first.
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "і": "i", "ї": "yi", "є": "ie", "ґ": "g", "ў": "u", "ђ": "dj", "ј": "j",
    "љ": "lj", "њ": "nj", "ћ": "c", "џ": "dz",
}
_GREEK = {
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th",
    "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p",
    "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y", "φ": "f", "χ": "ch", "ψ": "ps",
    "ω": "o",
}
# Consonants. Vowels are not in the Arabic script, so the result is a skeleton.
_ARABIC = {
    "ا": "a", "أ": "a", "إ": "a", "آ": "a", "ب": "b", "ت": "t", "ث": "th", "ج": "j",
    "ح": "h", "خ": "kh", "د": "d", "ذ": "dh", "ر": "r", "ز": "z", "س": "s", "ش": "sh",
    "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "q",
    "ك": "k", "ک": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "ة": "a", "و": "w",
    "ي": "y", "ی": "y", "ى": "a", "ئ": "y", "ؤ": "w", "ء": "", "پ": "p", "چ": "ch",
    "گ": "g", "ژ": "zh",
}
_TRANSLIT = {**_CYRILLIC, **_GREEK, **_ARABIC}

_PARTICLES = {
    "al", "el", "bin", "ibn", "ben", "bint", "abu", "abou",
    "van", "von", "de", "da", "di", "del", "della", "der", "den",
    "mr", "mrs", "ms", "dr", "sir", "jr", "sr",
    "sheikh", "shaikh", "shaykh", "sheik",
}
_PATRONYM = ("ovich", "evich", "yevich", "ovna", "evna", "yevna", "ovych", "evych", "yovych")
_CANON_GROUPS = (
    ("muhammad", "mohammed", "mohammad", "mohamed", "muhammed", "mohamad", "mohd", "muhamad"),
    ("yusuf", "yousef", "youssef", "yousuf"),
    ("aleksandr", "alexander", "aleksander"),
    ("aleksei", "alexei", "aleksey", "alexey"),
)
_CANON = {item: group[0] for group in _CANON_GROUPS for item in group}

_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]+")
_VOWELS = set("aeiouy")


def fold_name(value):
    """NFKC, casefold, drop combining marks. Punctuation is left for the tokenizer."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.casefold()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("’", "'").replace("`", "'")
    return text


def scripts_in(value):
    found = set()
    for ch in fold_name(value):
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if "CYRILLIC" in name:
            found.add("Cyrillic")
        elif "GREEK" in name:
            found.add("Greek")
        elif "ARABIC" in name:
            found.add("Arabic")
        elif "CJK" in name or "HIRAGANA" in name or "KATAKANA" in name or "HANGUL" in name:
            found.add("CJK")
        elif "LATIN" in name:
            found.add("Latin")
        else:
            found.add("Other")
    return found


def transliterate(text):
    return "".join(_TRANSLIT.get(ch, ch) for ch in text)


def _skeleton(token):
    return "".join(ch for ch in token if ch not in _VOWELS)


def skeleton_match(left, right):
    """Arabic writes consonants. Compare those to the consonant skeleton of a Latin token."""
    if not left or not right:
        return False
    left_bare = _skeleton(left) == left
    right_bare = _skeleton(right) == right
    if left_bare == right_bare:
        return False
    bare, full = (left, right) if left_bare else (right, left)
    if len(bare) < 4 or len(full) < 4:
        return False
    other = _skeleton(full)
    if not other:
        return False
    if bare == other:
        return True
    if abs(len(bare) - len(other)) > 1:
        return False
    # One insertion or deletion, nothing else. Deterministic and small.
    if len(bare) > len(other):
        bare, other = other, bare
    for index in range(len(other)):
        if bare == other[:index] + other[index + 1:]:
            return True
    return False


def _patronymic(token):
    return len(token) >= 7 and token.endswith(_PATRONYM)


def normalize_parts(value, is_company=False):
    """Tokens used for comparison. Order is kept; callers compare unordered."""
    if not value:
        return tuple()
    text = fold_name(value)
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
    cjk = tuple(dict.fromkeys(_CJK.findall(text)))
    text = _CJK.sub(" ", text)
    text = transliterate(text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    parts = []
    seen = set(cjk)
    for token in text.split():
        if len(token) <= 1 or token.isdigit():
            continue
        token = _CANON.get(token, token)
        if token in _PARTICLES or _patronymic(token):
            continue
        if token in {"na", "test", "unknown", "xxx", "none", "null", "nil"}:
            continue
        if token not in seen:
            seen.add(token)
            parts.append(token)
    return tuple(parts) + cjk


def native_excerpt(value, limit=48):
    """A short original-script snippet, or '' when the name is Latin."""
    chars = []
    for ch in str(value or ""):
        if ch.isalpha() and "LATIN" not in unicodedata.name(ch, "LATIN"):
            chars.append(ch)
        elif chars and ch.isspace():
            chars.append(" ")
    text = re.sub(r"\s+", " ", "".join(chars)).strip()
    if not text:
        return ""
    return text[:limit]


def _close_tokens(left, right):
    for a in left:
        for b in right:
            if a == b or any(ord(ch) > 127 for ch in a + b):
                continue
            if min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 2:
                continue
            if _distance(a, b) <= 2:
                return True
    return False


def _distance(left, right):
    if abs(len(left) - len(right)) > 2:
        return 3
    previous = list(range(len(right) + 1))
    for i, ch_left in enumerate(left, 1):
        current = [i]
        for j, ch_right in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (ch_left != ch_right)))
        previous = current
    return previous[-1]

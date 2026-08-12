"""Dedupe guard — keeps the same recipe from entering recipes.json twice.

Edna's guides overlap: several books reprint the same recipe, sometimes under a
slightly different title ("Sopa de frijoles negros" vs "Sopa de Frijoles Negros
(base cremosa)"). Before appending anything, check the candidate's name against
what is already stored and skip near-duplicates.

Usage:
  from dedupe import Deduper
  d = Deduper(existing_recipes)
  verdict = d.check(candidate)        # None if new, else the matched recipe
"""

import json
import os
import re
import unicodedata
from difflib import SequenceMatcher

# Above this name similarity, treat two recipes as the same dish.
NAME_THRESHOLD = 0.86

# Words that carry no distinguishing weight when comparing dish names.
# Function words only. Words like "clasica"/"citrica"/"casera" look decorative
# but are exactly what distinguishes one variant from another, so they stay.
STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "con", "y", "e", "o", "a", "al",
    "en", "para", "sin", "un", "una",
}


def norm(text: str | None) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    if not text:
        return ""
    t = "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def content_words(text: str | None) -> frozenset[str]:
    return frozenset(w for w in norm(text).split() if w not in STOPWORDS)


def name_similarity(a: str | None, b: str | None) -> float:
    """How alike two dish names are, by characters and by content words."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    seq = SequenceMatcher(None, na, nb).ratio()

    wa, wb = content_words(a), content_words(b)
    if not wa or not wb:
        return seq

    # Containment lets "Sopa de Frijoles Negros" match "... (base cremosa)",
    # but on its own it is dangerous: every word of "Salsa de Yogurt" is inside
    # "Hamburguesas de Pavo con Salsa de Yogurt", which is a different dish.
    # So only trust it when the two names are nearly the same length — a longer
    # name with extra content words is a different recipe, not a restatement.
    # A false positive silently drops a real recipe, which is worse than letting
    # a duplicate through where it stays visible and fixable.
    # Require at least two content words on the shorter side: with only one,
    # containment is meaningless — "Quinoa" sits inside "Tabouleh de quinoa"
    # without being the same dish.
    if (wa <= wb or wb <= wa) and min(len(wa), len(wb)) >= 2:
        if abs(len(wa) - len(wb)) <= 1:
            return 1.0
    return seq


class Deduper:
    """Tracks known recipe names and judges whether a candidate is new."""

    def __init__(self, existing: list[dict] | None = None):
        self.known: list[dict] = []
        for r in existing or []:
            self.add(r)

    def add(self, recipe: dict) -> None:
        self.known.append(recipe)

    def check(self, candidate: dict) -> dict | None:
        """Return the recipe this duplicates, or None when it is new."""
        name = candidate.get("name")
        if not name:
            return None
        best, score = None, 0.0
        for r in self.known:
            s = name_similarity(name, r.get("name"))
            if s > score:
                best, score = r, s
        return best if score >= NAME_THRESHOLD else None

    def filter(self, candidates: list[dict]) -> tuple[list[dict], list[tuple]]:
        """Split candidates into (new, skipped).

        Each skipped entry is (candidate, matched_existing). Accepted recipes
        are added to the known set as we go, so duplicates *within* the incoming
        batch are caught too.
        """
        new, skipped = [], []
        for c in candidates:
            match = self.check(c)
            if match is None:
                new.append(c)
                self.add(c)
            else:
                skipped.append((c, match))
        return new, skipped


def load_existing(path: str = "recipes.json") -> tuple[list[dict], dict]:
    """Read recipes.json, returning (recipes, whole_document).

    recipes.json holds {"recipes": [...], "tables": [...]} — the tables section
    must be preserved on write, so the caller gets the full document back too.
    """
    if not os.path.exists(path):
        return [], {}
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if isinstance(doc, list):
        return doc, {"recipes": doc}
    return doc.get("recipes", []), doc


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    recipes, _ = load_existing()
    print(f"recipes.json holds {len(recipes)} recipes")

    checks = [
        ("Sopa de Frijoles Negros (base cremosa)", "expect match if present"),
        ("Pechuga de Pollo a la Plancha", "expect match — in the workbook"),
        ("Pudding de Chía", "expect NEW"),
        ("Salsa Verde", "check it does not collide with Salsa de Tomate"),
    ]
    d = Deduper(recipes)
    for name, note in checks:
        m = d.check({"name": name})
        verdict = f"DUPLICATE of {m['name']!r}" if m else "new"
        print(f"  {name[:42]:<44} -> {verdict:<48} ({note})")

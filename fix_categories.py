"""One-off repair of the category field in recipes.json.

Three things:
  1. Re-derive categories for already-merged guide recipes using the fixed
     section matcher — the whole BASES section had been filed under PROTEÍNAS
     because the divider page says "BASES" while the index says
     "BASES (CARBOHIDRATOS)".
  2. Normalise casing across every recipe to one style: Title Case with Spanish
     connectors left lowercase ("Salsas y Aderezos", "Bases (Carbohidratos)").
  3. Re-file the aromatic bases (sofritos, mirepoix, sofregit) out of Proteínas —
     they are flavour bases, not a protein.

Usage:
  python fix_categories.py            # show what would change
  python fix_categories.py --apply
"""

import json
import re
import shutil
import sys
import unicodedata

from parse_guias import parse

# Left lowercase unless they start the name.
CONNECTORS = {
    "y", "e", "o", "u", "de", "del", "la", "el", "los", "las", "con", "a", "al",
    "en", "para", "sin", "sobre", "que",
}

# Aromatic bases that were filed under the protein section they sit in.
AROMATIC_BASES = ("sofrito", "mirepoix", "soffrito", "sofregit")
AROMATIC_CATEGORY = "Bases y Técnicas"


def titlecase(name: str) -> str:
    """Title Case a category, leaving Spanish connectors lowercase."""
    if not name:
        return name
    out = []
    for n, word in enumerate(re.split(r"(\s+|/)", name)):
        if not word.strip() or word == "/":
            out.append(word)
            continue
        bare = word.strip("()")
        wrap_open = "(" if word.startswith("(") else ""
        wrap_close = ")" if word.endswith(")") else ""
        low = bare.lower()
        if n > 0 and low in CONNECTORS:
            fixed = low
        elif bare == "&":
            fixed = "&"
        else:
            fixed = low[:1].upper() + low[1:]
        out.append(f"{wrap_open}{fixed}{wrap_close}")
    return "".join(out)


def norm_key(text: str | None) -> str:
    if not text:
        return ""
    t = "".join(c for c in unicodedata.normalize("NFD", text.lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    apply = "--apply" in sys.argv

    with open("recipes.json", encoding="utf-8") as fh:
        doc = json.load(fh)
    recipes = doc["recipes"]

    # Re-derive categories from the source PDFs with the fixed matcher.
    fresh: dict[str, str] = {}
    sources = {r["source_pdf"] for r in recipes if r.get("source_pdf")}
    for src in sorted(sources):
        for p in parse(src):
            if p["name"] and p["category"]:
                fresh[norm_key(p["name"])] = p["category"]
    print(f"  re-derived categories for {len(fresh)} parsed recipes "
          f"from {len(sources)} source PDF(s)")

    changes = []
    for r in recipes:
        before = r["category"]
        after = before

        if r.get("source_pdf"):
            after = fresh.get(norm_key(r["name"]), after)

        if any(k in norm_key(r["name"]) for k in AROMATIC_BASES):
            after = AROMATIC_CATEGORY

        after = titlecase(after)
        if after != before:
            changes.append((r["name"], before, after))
            r["category"] = after

    print(f"\n  {len(changes)} recipes change category:")
    for name, before, after in changes:
        print(f"      {str(name)[:40]:<42} {before!r:<26} -> {after!r}")

    counts: dict[str, int] = {}
    for r in recipes:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    print("\n  final categories:")
    for c, n in sorted(counts.items()):
        print(f"      {n:>3}  {c}")

    if apply:
        shutil.copy("recipes.json", "recipes.json.bak")
        doc["recipes"] = recipes
        with open("recipes.json", "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        print("\n  applied (backup: recipes.json.bak)")
    else:
        print("\n  dry run — re-run with --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())

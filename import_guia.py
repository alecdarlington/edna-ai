"""Stage recipes from one of Edna's newer guide PDFs for review, then merge.

Deliberately two-step: a run without --merge writes a staging file and prints
counts, samples and every dedupe decision, so the extraction can be reviewed
before the validated recipes.json is touched. Passing --merge appends the
accepted recipes (a .bak of recipes.json is written first).

The two model-derived fields (ingredients_normalized, difficulty) and
active_time_minutes are left null here; extract.py fills those in afterwards.
Total time comes straight from the PDF's RINDE/TIEMPO line, so it needs no model.

Usage:
  python import_guia.py "<file.pdf>"            # stage + report only
  python import_guia.py "<file.pdf>" --merge    # append into recipes.json
"""

import json
import os
import shutil
import sys

from dedupe import Deduper, load_existing
from parse_guias import key, load_index, load_lines, parse, similar

SCHEMA_FIELDS = [
    "name", "category", "servings", "ingredients", "ingredients_normalized",
    "steps", "active_time_minutes", "total_time_minutes", "difficulty",
    "notes", "source_pdf", "source_page",
]


def to_schema(r: dict) -> dict:
    """Shape a parsed recipe like the entries already in recipes.json."""
    return {
        "name": r["name"],
        "category": r["category"],
        "servings": r["servings"],
        "ingredients": r["ingredients"],
        "ingredients_normalized": None,   # extract.py fills this
        "steps": r["steps"],
        "active_time_minutes": None,      # extract.py fills this
        "total_time_minutes": r["total_time_minutes"],
        "difficulty": None,               # extract.py fills this
        "notes": r["notes"],
        "source_pdf": os.path.basename(r["source"]),
        "source_page": r["page"],
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_merge = "--merge" in sys.argv
    if not args:
        print(__doc__)
        return 1

    path = args[0]
    if "--recetas" in sys.argv:
        # Geometry-aware parser for the "Receta - <name>" layout, which has no
        # index to check coverage against.
        from parse_recetas import parse as parse_recetas
        parsed = parse_recetas(path)
        index_names = []
    else:
        parsed = parse(path)
        index_names, _ = load_index(load_lines(path))

    existing, doc = load_existing("recipes.json")
    deduper = Deduper(existing)
    candidates = [to_schema(r) for r in parsed]
    accepted, skipped = deduper.filter(candidates)

    W = 78
    print("=" * W)
    print(f"{os.path.basename(path)}")
    print("=" * W)
    print(f"  index lists          : {len(index_names)} recipes")
    print(f"  parsed               : {len(parsed)}")
    print(f"  already in recipes.json (skipped): {len(skipped)}")
    print(f"  new, ready to add    : {len(accepted)}")
    print(f"  recipes.json before  : {len(existing)}   after merge: "
          f"{len(existing) + len(accepted)}")

    # Coverage against the book's own index.
    def covered(name):
        return any(
            similar(name, p["name"]) >= 0.75
            or (set(key(name).split()) and
                len(set(key(name).split()) & set(key(p["name"]).split()))
                / len(set(key(name).split())) >= 0.75)
            for p in parsed
        )

    missed = [n for n in index_names if not covered(n)]
    print(f"  index entries not parsed: {len(missed)}")
    for n in missed:
        print(f"      ! {n}")

    print("\n  DEDUPE SKIPS")
    if not skipped:
        print("      (none)")
    for c, m in skipped:
        print(f"      {str(c['name'])[:40]:<42} == existing {str(m['name'])[:32]!r}")

    print("\n  DATA QUALITY (parsed)")
    print(f"      missing name       : {sum(1 for r in parsed if not r['name'])}")
    print(f"      missing ingredients: {sum(1 for r in parsed if not r['ingredients'])}")
    print(f"      missing steps      : {sum(1 for r in parsed if not r['steps'])}")
    print(f"      missing total time : {sum(1 for r in parsed if not r['total_time_minutes'])}")
    cats = {}
    for r in parsed:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    print(f"      categories         : {cats}")

    stage = f"staged_{os.path.splitext(os.path.basename(path))[0][:38]}.json"
    with open(stage, "w", encoding="utf-8") as fh:
        json.dump(accepted, fh, ensure_ascii=False, indent=2)
    print(f"\n  staged -> {stage}")

    if do_merge:
        shutil.copy("recipes.json", "recipes.json.bak")
        doc["recipes"] = existing + accepted
        with open("recipes.json", "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        print(f"  MERGED into recipes.json ({len(doc['recipes'])} recipes); "
              f"backup at recipes.json.bak")
    else:
        print("  (not merged — re-run with --merge to append)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

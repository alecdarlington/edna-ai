"""Append an enriched staged_*.json into recipes.json.

Separate from import_guia.py on purpose: that script re-parses the PDF, which
would discard the enrichment written by enrich_staged.py. This one merges the
staged file exactly as reviewed.

Refuses to merge records missing ingredients_normalized, because the ingredient
search in search.py depends on that field.

Usage:
  python merge_staged.py staged_file.json
"""

import json
import shutil
import sys

from dedupe import Deduper, load_existing


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    stage = sys.argv[1]
    with open(stage, encoding="utf-8") as fh:
        incoming = json.load(fh)

    # Guard: the search layer needs ingredients_normalized on every record.
    unenriched = [r for r in incoming if not r.get("ingredients_normalized")]
    if unenriched:
        print(f"REFUSING TO MERGE — {len(unenriched)} records have no "
              f"ingredients_normalized. Run enrich_staged.py first.")
        for r in unenriched[:10]:
            print(f"    {r.get('name')}")
        return 1

    misaligned = [r for r in incoming
                  if len(r["ingredients_normalized"]) != len(r["ingredients"])]
    if misaligned:
        print(f"REFUSING TO MERGE — {len(misaligned)} records where "
              f"ingredients_normalized does not align 1:1 with ingredients.")
        for r in misaligned[:10]:
            print(f"    {r.get('name')}")
        return 1

    existing, doc = load_existing("recipes.json")
    accepted, skipped = Deduper(existing).filter(incoming)

    print(f"  recipes.json before : {len(existing)}")
    print(f"  staged (enriched)   : {len(incoming)}")
    print(f"  skipped as duplicate: {len(skipped)}")
    for c, m in skipped:
        print(f"      {str(c['name'])[:40]:<42} == {str(m['name'])[:34]!r}")
    print(f"  appended            : {len(accepted)}")

    shutil.copy("recipes.json", "recipes.json.bak")
    doc["recipes"] = existing + accepted
    with open("recipes.json", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)

    print(f"  recipes.json after  : {len(doc['recipes'])}  "
          f"(tables preserved: {len(doc.get('tables', []))})")
    print("  backup: recipes.json.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())

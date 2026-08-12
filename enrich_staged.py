"""Fill the model-derived fields on staged recipes, in place.

Runs extract.py's existing Claude pass over a staged_*.json file to populate
ingredients_normalized, active_time_minutes and difficulty. The ingredient
search depends on ingredients_normalized, so nothing should be merged into
recipes.json until this has run.

total_time_minutes read from the PDF's RINDE/TIEMPO line is authoritative and is
kept; the model only supplies it where the PDF gave none.

Recipes with no ingredient list (the sofritos, whose ingredients are written
inline in prose) go through extract.py's embed prompt, which reads them out of
the step text and returns both lists.

Usage:
  python enrich_staged.py staged_file.json
"""

import json
import sys

from extract import build_client, enrich_llm, enrich_rule, load_api_key


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    path = sys.argv[1]
    with open(path, encoding="utf-8") as fh:
        recipes = json.load(fh)

    key = load_api_key()
    if not key:
        print("No ANTHROPIC_API_KEY found — cannot run the enrichment pass.")
        return 1
    client = build_client(key)

    llm_ok = rule_ok = 0
    failures = []
    for n, rec in enumerate(recipes, 1):
        # enrich_llm expects these keys; staged records already carry them.
        probe = {
            "name": rec["name"],
            "category": rec["category"],
            "ingredients": rec["ingredients"],
            "steps": rec["steps"],
        }
        try:
            data = enrich_llm(client, probe)
            llm_ok += 1
        except Exception as e:                      # fall back rather than fail
            data = enrich_rule(probe)
            rule_ok += 1
            failures.append((rec["name"], str(e)[:70]))

        # The embed path returns the ingredient list it recovered from the steps.
        recovered = data.get("ingredients")
        if recovered and not rec["ingredients"]:
            rec["ingredients"] = recovered

        rec["ingredients_normalized"] = data.get("ingredients_normalized") or []
        rec["active_time_minutes"] = data.get("active_time_minutes")
        rec["difficulty"] = data.get("difficulty")
        # Keep the PDF's own total time; only fill a gap.
        if not rec.get("total_time_minutes"):
            rec["total_time_minutes"] = data.get("total_time_minutes")

        flag = "" if len(rec["ingredients_normalized"]) == len(rec["ingredients"]) \
            else "  <-- LENGTH MISMATCH"
        print(f"  [{n:03d}/{len(recipes)}] {str(rec['name'])[:44]:<46} "
              f"ing={len(rec['ingredients']):<3} norm="
              f"{len(rec['ingredients_normalized']):<3} "
              f"act={str(rec['active_time_minutes']):<5} "
              f"tot={str(rec['total_time_minutes']):<5} "
              f"{str(rec['difficulty'])[:11]}{flag}")

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(recipes, fh, ensure_ascii=False, indent=2)

    misaligned = [r for r in recipes
                  if len(r["ingredients_normalized"]) != len(r["ingredients"])]
    missing_norm = [r for r in recipes if not r["ingredients_normalized"]]
    print(f"\n  enriched via Claude: {llm_ok}   via rule fallback: {rule_ok}")
    print(f"  1:1 alignment failures: {len(misaligned)}")
    for r in misaligned:
        print(f"      {str(r['name'])[:46]:<48} "
              f"{len(r['ingredients'])} ing vs {len(r['ingredients_normalized'])} norm")
    print(f"  still without ingredients_normalized: {len(missing_norm)}")
    for r in missing_norm:
        print(f"      {str(r['name'])[:46]}")
    if failures:
        print("  fallback reasons:")
        for name, err in failures[:8]:
            print(f"      {str(name)[:40]:<42} {err}")
    print(f"\n  written back to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

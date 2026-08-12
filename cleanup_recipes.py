"""Post-merge cleanup of recipes.json.

  1. Re-parse Meal-Planning with the fixed heading patterns and patch records
     that were merged with missing steps. The steps were never on a facing page:
     those recipes head them "Procedimiento de Salsa", which the anchored
     pattern missed.
  2. Move a yield phrase ("Hace ½ taza") out of the ingredient list into
     servings, and clamp active_time to total_time where the estimate exceeded it.
  3. Re-run the enrichment pass on every patched record so
     ingredients_normalized stays 1:1 with the corrected ingredient list.
  4. Merge duplicate categories: Sopas -> Caldos & Sopas, and
     Bases (Carbohidratos) -> Granos.
  5. Report the source page of any recipe left with a broken title.

Usage:
  python cleanup_recipes.py            # dry run
  python cleanup_recipes.py --apply
"""

import json
import re
import shutil
import sys
import unicodedata

from dedupe import norm
from extract import build_client, enrich_llm, enrich_rule, load_api_key
from parse_recetas import SERV_RE, parse

MEAL_PLANNING = "Guia-Meal-Planning-EdnaCochez-2025V4.pdf"

# One category per concept. Values are the surviving names.
CATEGORY_MERGES = {
    "sopas": "Caldos & Sopas",
    "bases (carbohidratos)": "Granos",
}

# A title is suspect if it starts lowercase, ends mid-phrase, or is too short.
BROKEN_TITLE_RE = re.compile(r"^[a-z¡!¿?)\]]|[(\[]$|^.{0,4}$|[!)\]]$")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    apply = "--apply" in sys.argv

    with open("recipes.json", encoding="utf-8") as fh:
        doc = json.load(fh)
    recipes = doc["recipes"]

    # ── 1. patch missing steps from a fresh parse ───────────────────────────
    fresh = {norm(r["name"]): r for r in parse(MEAL_PLANNING) if r["name"]}
    print(f"  re-parsed Meal-Planning: {len(fresh)} recipes")

    patched = []
    for r in recipes:
        if not r.get("steps"):
            src = fresh.get(norm(r["name"]))
            if src and src["steps"]:
                r["steps"] = src["steps"]
                r["notes"] = (r.get("notes") or []) + (src["notes"] or [])
                patched.append((r["name"], f"+{len(src['steps'])} steps"))

    # ── 2. yield phrases parked in the ingredient list ──────────────────────
    for r in recipes:
        keep, moved = [], None
        for ing in r.get("ingredients") or []:
            m = SERV_RE.match(ing)
            if m and len(ing) < 40:
                moved = moved or m.group(1).strip().rstrip(".")
                continue
            keep.append(ing)
        if moved:
            r["ingredients"] = keep
            if not r.get("servings"):
                r["servings"] = moved
            patched.append((r["name"], f"yield {moved!r} out of ingredients"))

    # ── 3. re-enrich everything touched ─────────────────────────────────────
    names = {n for n, _ in patched}
    todo = [r for r in recipes if r["name"] in names]
    print(f"\n  {len(patched)} patches across {len(todo)} recipes:")
    for name, what in patched:
        print(f"      {str(name)[:44]:<46} {what}")

    if todo and apply:
        key = load_api_key()
        client = build_client(key) if key else None
        for r in todo:
            probe = {k: r[k] for k in ("name", "category", "ingredients", "steps")}
            try:
                data = enrich_llm(client, probe) if client else enrich_rule(probe)
            except Exception:
                data = enrich_rule(probe)
            recovered = data.get("ingredients")
            if recovered and not r["ingredients"]:
                r["ingredients"] = recovered
            r["ingredients_normalized"] = data.get("ingredients_normalized") or []
            r["active_time_minutes"] = data.get("active_time_minutes")
            r["difficulty"] = data.get("difficulty") or r.get("difficulty")
            if not r.get("total_time_minutes"):
                r["total_time_minutes"] = data.get("total_time_minutes")
            print(f"      re-enriched {str(r['name'])[:40]:<42} "
                  f"ing={len(r['ingredients'])} norm={len(r['ingredients_normalized'])}")

    # active time can never exceed total time
    clamped = 0
    for r in recipes:
        a, t = r.get("active_time_minutes"), r.get("total_time_minutes")
        if a and t and a > t:
            r["active_time_minutes"] = t
            clamped += 1
    print(f"\n  clamped active>total on {clamped} recipes")

    # ── 4. category merges ─────────────────────────────────────────────────
    moves = 0
    for r in recipes:
        target = CATEGORY_MERGES.get((r.get("category") or "").lower())
        if target:
            r["category"] = target
            moves += 1
    print(f"  category merges applied to {moves} recipes")

    # ── 5. report broken titles ────────────────────────────────────────────
    print("\n  suspect titles (for manual reconstruction):")
    for r in recipes:
        n = (r.get("name") or "").strip()
        if BROKEN_TITLE_RE.search(n):
            print(f"      {n!r:<34} category={r.get('category')!r} "
                  f"source={str(r.get('source_pdf'))[:30]} page={r.get('source_page')}")

    counts: dict[str, int] = {}
    for r in recipes:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    print("\n  final categories:")
    for c, n in sorted(counts.items()):
        print(f"      {n:>3}  {c}")
    print(f"\n  recipes without steps: {sum(1 for r in recipes if not r.get('steps'))}")
    print(f"  misaligned normalized: "
          f"{sum(1 for r in recipes if r.get('ingredients') and len(r.get('ingredients_normalized') or []) != len(r['ingredients']))}")

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

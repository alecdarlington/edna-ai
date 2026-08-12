"""test_search.py — five evaluation questions for the search layer."""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from search import route_question, search_recipes, search_theory

# ── Test cases ─────────────────────────────────────────────────────────────────
# ings: ingredients to pass to search_recipes (empty = no pantry stated)
# min_coverage: override default 0.30 when pantry is very small
CASES = [
    {
        "q":    "Tengo tomate, ajo y pollo, ¿qué puedo hacer?",
        "ings": ["tomate", "ajo", "pollo"],
    },
    {
        "q":    "¿Cuál receta es la más rápida?",
        "ings": [],          # no pantry — show all, sorted by time
    },
    {
        "q":    "¿Cuánta sal le pongo a la carne?",
        "ings": [],
    },
    {
        "q":    "¿Qué ensalada puedo hacer y por qué lleva ácido?",
        "ings": [],
    },
    {
        "q":    "Tengo leche, ¿qué puedo hacer?",
        "ings": ["leche"],
        "min_coverage": 0.10,   # single ingredient → lower threshold
    },
]

W = 68

for i, case in enumerate(CASES, 1):
    q    = case["q"]
    ings = case["ings"]
    mc   = case.get("min_coverage", 0.30)

    route = route_question(q)
    s, rh, th = route["scores"], route["recipe_hints"], route["theory_hints"]

    print(f"\n{'═' * W}")
    print(f"  Q{i}: {q}")
    print(f"{'═' * W}")
    print(f"  Ruta    : {route['type'].upper():<9}  "
          f"receta={s['recipe']}  técnica={s['technique']}")
    print(f"  Hints   : cat={rh['category'] or '—'}  "
          f"tiempo={'Sí' if rh['sort_by_time'] else 'No'}  "
          f"pilar={th['pillar'] or '—'}")
    if ings:
        print(f"  Ingred. : {', '.join(ings)}")
    if mc != 0.30:
        print(f"  (min_coverage={mc})")

    # ── Recipe results ────────────────────────────────────────────────────────
    if route["type"] in ("recipe", "both"):
        kw: dict = dict(
            category=rh["category"],
            sort_by_time=rh["sort_by_time"],
            min_coverage=mc if ings else 0.0,
        )
        hits = search_recipes(ings, **kw)
        order = "↑ tiempo" if rh["sort_by_time"] else "↓ cobertura"
        print(f"\n  ── Recetas ({order}, top 5) {'─' * 36}")
        if not hits:
            print("    (sin resultados)")
        for j, r in enumerate(hits, 1):
            pct  = f"{r['have_pct']*100:.0f}%" if r["have_pct"] > 0 else " —"
            miss = r["missing"]
            miss_str = (", ".join(miss[:3]) + (f" (+{len(miss)-3} más)" if len(miss) > 3 else "")) if miss else "ninguno"
            print(f"  {j}. {pct:>4}  {r['name']:<44} {r['total_time_minutes']:>4} min")
            print(f"        faltan: {miss_str}")

    # ── Theory results ────────────────────────────────────────────────────────
    if route["type"] in ("technique", "both"):
        hits = search_theory(q, pillar=th["pillar"])
        pil_label = th["pillar"] or "todos"
        print(f"\n  ── Teoría (pilar: {pil_label}) {'─' * 40}")
        if not hits:
            print("    (sin resultados)")
        for j, r in enumerate(hits, 1):
            snippet = r["content"][:100].replace("\n", " ")
            print(f"  {j}. [{r['score']:2d}] [{r['pillar']:6s}]  {r['topic']}")
            print(f"        «{snippet}…»")

print(f"\n{'═' * W}")
print("  Fin.")
print(f"{'═' * W}\n")

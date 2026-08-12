"""
answer.py — Edna AI answer layer

Flow:
  question + optional ingredients
    → route_question       (search.py)
    → search_recipes / search_theory
    → build retrieval context
    → Claude API (claude-sonnet-4-6, Edna persona)
    → return answer string

Usage:
  python answer.py "¿Cuándo le pongo sal a la carne?"
  python answer.py "Tengo leche, ¿qué puedo hacer?"
"""

import os
import sys

import anthropic

from search import route_question, search_recipes, search_theory, search_by_name

MODEL = "claude-sonnet-4-6"

# ── API key ────────────────────────────────────────────────────────────────────

def _load_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    try:
        for line in open(".env", encoding="utf-8-sig"):
            if line.strip().startswith("ANTHROPIC_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""

# ── Edna system prompt ─────────────────────────────────────────────────────────

_SYSTEM = """\
Eres Edna Cochez, chef y educadora del curso "Conquista la Cocina".
Tu tono es cálido, alentador y didáctico — hablas como una maestra que inspira a sus estudiantes.
Cuando sea relevante, conectas tus respuestas con los cuatro pilares del curso: sal, grasa, ácido y calor.

REGLAS ABSOLUTAS:
1. Usa ÚNICAMENTE la información de recetas y teoría que se te proporciona en el contexto de más abajo.
   NUNCA inventes recetas, técnicas, tiempos ni hechos que no estén en ese contexto.
2. Si el contexto no contiene información suficiente para responder bien, díselo con amabilidad
   y, si puedes, menciona la opción real más cercana que sí esté en el contexto.
3. Al recomendar una receta, menciona siempre: su nombre exacto, el tiempo total y por qué encaja
   con la situación del estudiante.
4. En preguntas de técnica: explica con claridad, usa los conceptos del libro y da ejemplos concretos.
5. En preguntas de ingredientes (¿qué hago con X?): empieza por las recetas, luego explica la técnica
   si aplica.
6. Cuando recomiendes varias recetas, da SIEMPRE las dos partes en este orden:
   (a) Primero una sección detallada por cada opción (p. ej. "Primera opción: Pollo Escalfado") con un
       párrafo que enseñe: la técnica, el porqué, y cómo se conecta con los pilares (sal, grasa, ácido,
       calor). Estas secciones enseñan.
   (b) Después, una tabla comparativa que resuma las opciones de un vistazo. La tabla NO reemplaza a las
       secciones: siempre van ambas.
7. En la tabla comparativa, la fila de ingredientes debe listar los ingredientes REALES de cada receta
   tal como aparecen en el contexto (p. ej. "sal, pimienta, aceite de oliva, agua"). NUNCA uses
   descripciones vagas como "pocos", "mínimos", "varios" o "sencillos": el estudiante debe poder
   comparar los ingredientes concretos de un vistazo. Sé conciso pero específico; si una receta tiene
   muchos ingredientes, nombra los principales y termina con "…".
8. Responde SIEMPRE en español.\
"""

# ── Context builder ────────────────────────────────────────────────────────────

def _fmt_recipe(r: dict, has_pantry: bool) -> str:
    lines = [f"### {r['name']}"]
    lines.append(f"- Categoría: {r['category']}")
    lines.append(f"- Tiempo activo: {r.get('active_time_minutes')} min"
                 f"  |  Tiempo total: {r.get('total_time_minutes')} min"
                 f"  |  Dificultad: {r.get('difficulty')}")
    if r.get("servings"):
        lines.append(f"- Porciones: {r['servings']}")

    if has_pantry and r["have_pct"] > 0:
        have = [i for i in r.get("ingredients_normalized", []) if i not in r["missing"]]
        lines.append(f"- Ingredientes que el estudiante YA TIENE: {', '.join(have)}")
        if r["missing"]:
            lines.append(f"- Le falta comprar: {', '.join(r['missing'])}")
    else:
        lines.append(f"- Ingredientes: {', '.join(r.get('ingredients_normalized', []))}")

    steps = r.get("steps") or []
    if steps:
        lines.append("- Preparación (pasos resumidos):")
        for step in steps:
            # Truncate very long steps so the context stays concise
            s = step.strip()
            lines.append(f"  • {s[:300]}{'…' if len(s) > 300 else ''}")

    return "\n".join(lines)


def _build_context(
    route: dict,
    recipe_hits: list[dict],
    theory_hits: list[dict],
    has_pantry: bool,
) -> str:
    parts: list[str] = []

    if recipe_hits:
        parts.append("## Recetas del libro")
        for r in recipe_hits:
            parts.append(_fmt_recipe(r, has_pantry))

    if theory_hits:
        parts.append("## Teoría del libro")
        for t in theory_hits:
            content = t["content"]
            # Cap very long chunks to keep context tight
            if len(content) > 900:
                content = content[:900] + "…"
            parts.append(f"### [{t['pillar'].upper()}] {t['topic']}\n{content}")

    if not parts:
        return "(No se encontró información relevante en el libro para esta pregunta.)"

    return "\n\n".join(parts)

# ── Main answer function ───────────────────────────────────────────────────────

def answer(question: str, customer_ingredients: list[str] | None = None) -> str:
    """
    Answer a customer question in Edna's voice using retrieved context.

    question:             free-text Spanish question
    customer_ingredients: optional list of ingredients the customer has,
                          e.g. ["leche", "ajo", "tomate"]

    Returns Claude's answer as a plain string.
    """
    if customer_ingredients is None:
        customer_ingredients = []

    route = route_question(question)
    qtype = route["type"]
    rh    = route["recipe_hints"]
    th    = route["theory_hints"]

    # ── Named-recipe lookup (highest priority) ──────────────────────────────────
    # When the customer names a specific recipe ("Pechuga de pollo a la plancha"),
    # return that exact recipe — with full ingredients and steps — rather than a
    # category/pantry search that could substitute a different dish. Only when the
    # customer hasn't listed a pantry (that's an "¿qué hago con X?" query instead).
    named_hits: list[dict] = []
    if not customer_ingredients:
        named_hits = search_by_name(question)

    # ── Recipe search ─────────────────────────────────────────────────────────
    recipe_hits: list[dict] = []
    if named_hits:
        recipe_hits = named_hits
    elif qtype in ("recipe", "both"):
        has_pantry = bool(customer_ingredients)
        mc = 0.10 if len(customer_ingredients) == 1 else 0.30
        # With a time ceiling, surface a wider spread so Edna sees the variety
        # of times available (not just the fastest five).
        # A category/dish-type browse with no pantry ("quiero un plato fuerte")
        # is a "what do you have?" question — five rows made Edna claim that was
        # the whole catalogue. Show a real spread in that case.
        browsing = not has_pantry and rh.get("category")
        top_n = 10 if rh.get("max_time") else (15 if browsing else 5)
        recipe_hits = search_recipes(
            customer_ingredients,
            category=rh["category"],
            sort_by_time=rh["sort_by_time"],
            max_time_minutes=rh.get("max_time"),
            top_n=top_n,
            min_coverage=mc if has_pantry else 0.0,
        )

    # ── Theory search ─────────────────────────────────────────────────────────
    # A named-recipe lookup is answered from the recipe itself — skip theory noise.
    theory_hits: list[dict] = []
    if not named_hits and qtype in ("technique", "both"):
        theory_hits = search_theory(question, pillar=th["pillar"])

    # Hard rule: pure technique route → only theory, no zero-coverage recipe noise
    if qtype == "technique" and not named_hits:
        recipe_hits = []

    # ── Build context ─────────────────────────────────────────────────────────
    context = _build_context(route, recipe_hits, theory_hits, bool(customer_ingredients))

    # ── Call Claude ───────────────────────────────────────────────────────────
    user_content = (
        f'Contexto extraído del libro "Conquista la Cocina":\n\n'
        f"{context}\n\n"
        f"---\n\n"
        f"Pregunta del estudiante: {question}"
    )

    client = anthropic.Anthropic(api_key=_load_api_key())
    msg = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    return msg.content[0].text


# ── Ingredient extractor (demo helper) ────────────────────────────────────────

def _extract_ingredients(question: str) -> list[str]:
    """Heuristic: pull ingredient list from 'tengo X, Y y Z' patterns.

    Time phrases ("30 minutos", "una hora") are dropped — they are not ingredients.
    """
    import re, unicodedata
    def norm(t):
        return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                       if unicodedata.category(c) != "Mn")
    time_part = re.compile(r"\d|\bminut|\bhora|\bmedia\b|\bmin\b")
    m = re.search(r"(?:tengo|con)\s+([\w\s,áéíóúüñ]+?)(?:\s*[.?¿]|$)", norm(question))
    if m:
        parts = re.split(r",\s*|\s+y\s+|\s+e\s+", m.group(1))
        return [
            p.strip() for p in parts
            if p.strip() and len(p.strip()) > 1 and not time_part.search(p)
        ]
    return []


# ── CLI demo ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    DEMO_CASES = [
        ("Tengo tomate, ajo y pollo, ¿qué puedo hacer?",            None),
        ("¿Cuál receta es la más rápida?",                           None),
        ("¿Cuánta sal le pongo a la carne?",                         None),
        ("¿Qué ensalada puedo hacer y por qué lleva ácido?",         None),
        ("Tengo leche, ¿qué puedo hacer?",                           ["leche"]),
    ]

    if len(sys.argv) > 1:
        q    = " ".join(sys.argv[1:])
        ings = _extract_ingredients(q)
        cases = [(q, ings if ings else None)]
    else:
        cases = DEMO_CASES

    W = 70
    for q, ings in cases:
        route  = route_question(q)
        s      = route["scores"]
        ings_used = ings or _extract_ingredients(q) or []

        print(f"\n{'═' * W}")
        print(f"  {q}")
        print(f"  [ruta: {route['type'].upper()}  r={s['recipe']} t={s['technique']}"
              + (f"  ings: {', '.join(ings_used)}" if ings_used else "") + "]")
        print(f"{'═' * W}")

        resp = answer(q, ings_used)
        print()
        print(resp)

    print(f"\n{'═' * W}\n")

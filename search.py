"""
search.py — edna-ai search layer

Three public functions:
  search_recipes(ingredients, *, category, sort_by_time, top_n, min_coverage)
  search_theory(question, *, pillar, top_n)
  route_question(question) -> dict
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

# ── Load data ──────────────────────────────────────────────────────────────────

_BASE = Path(__file__).parent

with (_BASE / "recipes.json").open(encoding="utf-8") as _f:
    _rdata = json.load(_f)
RECIPES: list[dict] = _rdata["recipes"]

with (_BASE / "theory.json").open(encoding="utf-8") as _f:
    _tdata = json.load(_f)
CHUNKS: list[dict] = _tdata["chunks"]

# ── Normalisation helpers ──────────────────────────────────────────────────────

_STOP = {
    "de", "la", "el", "los", "las", "un", "una", "con", "sin", "y", "o",
    "en", "a", "al", "del", "lo", "se", "es", "su", "sus", "por", "para",
    "que", "mas", "muy", "mas", "hay", "como",
    # Request framing, not content. "receta de albóndigas" must count as one
    # meaningful word, otherwise the name search demands two matches and finds
    # nothing even though the dish exists.
    "receta", "recetas", "recetario", "hacer", "haces", "preparar", "preparo",
    "quiero", "quisiera", "dame", "tienes", "tiene", "tengo", "alguna",
    "algun", "alguno", "puedo", "puedes", "porfavor", "favor",
}


def _norm(text: str) -> str:
    """Lowercase + strip combining diacritics (á→a, etc.)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


def _is_alternative(ing: str) -> bool:
    """True when an ingredient line offers a choice, e.g.
    "tofu sedoso o mayonesa de aceite de aguacate" or "mantequilla / aceite".

    Matching one side of an either/or is weaker evidence that the customer can
    actually make the dish than matching an ingredient it truly requires.
    """
    return bool(re.search(r"\s+o\s+|\s*/\s*", _norm(ing)))


def _words(text: str, min_len: int = 3) -> set[str]:
    """Significant words: normalised, ≥min_len chars, not stopwords."""
    return {
        w for w in re.findall(r"[a-z]+", _norm(text))
        if len(w) >= min_len and w not in _STOP
    }


# Spanish number words for "X hora(s)" / "X minutos" phrasing
_NUM_WORDS = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "media": 0.5,
}


def detect_max_time(text: str) -> Optional[int]:
    """
    Detect an available-time limit in a question, return it in minutes.

    Handles: "30 minutos", "30 min", "1 hora", "2 horas", "media hora",
             "hora y media", "una hora", "hora y cuarto".
    Returns None when no time limit is mentioned.
    """
    q = _norm(text)

    # "hora y media" / "hora y cuarto" → 90 / 75
    if re.search(r"\bhora\s+y\s+media\b", q):
        return 90
    if re.search(r"\bhora\s+y\s+cuarto\b", q):
        return 75

    # "<n> hora(s)"  — digit or number word
    m = re.search(r"\b(\d+|" + "|".join(_NUM_WORDS) + r")\s+horas?\b", q)
    if m:
        val = _NUM_WORDS.get(m.group(1), None)
        if val is None:
            val = float(m.group(1))
        return int(val * 60)

    # "media hora"
    if re.search(r"\bmedia\s+hora\b", q):
        return 30

    # "<n> minuto(s)" / "<n> min"
    m = re.search(r"\b(\d+)\s*(?:minutos?|mins?\b)", q)
    if m:
        return int(m.group(1))

    return None


# ── 1. Recipe search ───────────────────────────────────────────────────────────

def search_recipes(
    customer_ingredients: list[str],
    *,
    category: Optional[str | list[str]] = None,
    sort_by_time: bool = False,
    max_time_minutes: Optional[int] = None,
    top_n: int = 5,
    min_coverage: float = 0.30,
) -> list[dict]:
    """
    Find recipes the customer can make given their ingredients.

    customer_ingredients: list of plain-text items, e.g. ["pollo", "cebolla"]
    category:             exact category name, a list of category names (any of
                          which matches — used for dish-type groups like
                          "plato fuerte" → mains), or None for all categories
    sort_by_time:         True → sort by total_time_minutes asc ("¿cuál es la más rápida?")
    max_time_minutes:     drop recipes whose total_time_minutes exceeds this limit
                          ("tengo 30 minutos…"); None = no time limit
    min_coverage:         drop recipes where fewer than this fraction of their
                          ingredients are covered by the customer's pantry

    Each result dict is the original recipe dict plus:
      have_count        — number of recipe ingredients the customer has
      total_ingredients — total ingredients in the recipe
      have_pct          — have_count / total_ingredients (0–1)
      missing           — list of ingredient names the customer is missing
    """
    # Build a flat word-set from all customer ingredients for fast matching
    customer_words: set[str] = set()
    for ing in customer_ingredients:
        customer_words |= _words(ing)

    def _covered(ing: str) -> bool:
        """True if any ingredient word prefix-matches any customer word (handles plurals)."""
        if not customer_words:
            return False
        for iw in _words(ing):
            for cw in customer_words:
                if iw == cw:
                    return True
                # prefix match ≥4 chars covers huevo/huevos, limón/limones, etc.
                mn = min(len(iw), len(cw))
                if mn >= 4 and iw[:mn] == cw[:mn]:
                    return True
        return False

    # Normalise the category filter to a set (accepts a single name or a group)
    cat_filter: Optional[set[str]] = None
    if category:
        cats = [category] if isinstance(category, str) else list(category)
        cat_filter = {_norm(c) for c in cats}

    results: list[dict] = []
    for recipe in RECIPES:
        if cat_filter is not None and _norm(recipe["category"]) not in cat_filter:
            continue

        if max_time_minutes is not None:
            total = recipe.get("total_time_minutes")
            if total is None or total > max_time_minutes:
                continue

        norm_ings: list[str] = recipe.get("ingredients_normalized") or []
        if not norm_ings:
            continue

        have: list[str] = []
        missing: list[str] = []
        for ing in norm_ings:
            if _covered(ing):
                have.append(ing)
            else:
                missing.append(ing)

        have_pct = len(have) / len(norm_ings)

        # A dish named after one of the customer's ingredients is *about* that
        # ingredient, so it must not be filtered out just because it also needs
        # eleven other things: "Scramble de Tofu" scores 1/12 = 0.08 on coverage
        # alone and would lose to a recipe that merely lists tofu as an option.
        name_words = _words(recipe.get("name") or "")
        named_for_pantry = bool(_name_overlap(customer_words, name_words))

        # Drop a recipe only when the evidence is genuinely weak: every pantry
        # match came from an either/or ingredient line AND the dish is named
        # after something the customer lacks. That is exactly "Ensalada de atún"
        # for "tengo tofu" — tofu is listed as an alternative to mayonnaise, and
        # the tuna it is named for is missing. A primary match such as milk in
        # "Crema de Zapallo" stays, since that is a real answer to "tengo leche".
        weak_only = bool(have) and all(_is_alternative(i) for i in have)
        if customer_words and not named_for_pantry and weak_only:
            if any(_name_overlap(_words(ing), name_words) for ing in missing):
                continue
        if not named_for_pantry and have_pct < min_coverage:
            continue

        results.append({
            **recipe,
            "have_count": len(have),
            "total_ingredients": len(norm_ings),
            "have_pct": round(have_pct, 2),
            "missing": missing,
            "named_for_pantry": named_for_pantry,
        })

    if sort_by_time or max_time_minutes is not None:
        results.sort(key=lambda r: r.get("total_time_minutes") or 9999)
    else:
        # Name matches first: the dish the customer's ingredient is named after
        # is the most useful answer, then by coverage.
        results.sort(key=lambda r: (not r["named_for_pantry"],
                                    -r["have_pct"], -r["have_count"]))

    return results[:top_n]


# ── 1b. Recipe-name search ───────────────────────────────────────────────────────

def _name_overlap(q_words: set[str], name_words: set[str]) -> set[str]:
    """Query words that appear in a recipe name, tolerant of plurals/accents.

    Accents are already stripped by _words(); this adds prefix matching (≥4 chars)
    so "pescados"/"pescado", "pechugas"/"pechuga" still line up.
    """
    matched: set[str] = set()
    for qw in q_words:
        for nw in name_words:
            if qw == nw:
                matched.add(qw)
                break
            mn = min(len(qw), len(nw))
            if mn >= 4 and qw[:mn] == nw[:mn]:
                matched.add(qw)
                break
    return matched


_COMMON_ING_CACHE: set[str] | None = None


def _common_ingredient_words(min_recipes: int = 3) -> set[str]:
    """Words that behave like pantry staples rather than dish names.

    Built from the corpus: a term that several different recipes list as an
    ingredient is an ingredient. Used to decide whether a lone query word should
    be read as naming a dish.
    """
    global _COMMON_ING_CACHE
    if _COMMON_ING_CACHE is None:
        counts: dict[str, int] = {}
        for r in RECIPES:
            seen: set[str] = set()
            for ing in r.get("ingredients_normalized") or []:
                seen |= _words(ing)
            for w in seen:
                counts[w] = counts.get(w, 0) + 1
        _COMMON_ING_CACHE = {w for w, n in counts.items() if n >= min_recipes}
    return _COMMON_ING_CACHE


def search_by_name(
    query: str,
    *,
    top_n: int = 3,
    min_matched: int = 2,
    min_query_coverage: float = 0.5,
) -> list[dict]:
    """
    Find recipes the customer named directly, e.g. "Pechuga de pollo a la plancha".

    Matches the customer's significant words against each recipe's NAME, tolerant of
    word order, accents, capitalisation, and partial names. A recipe is considered
    "named" only when at least `min_matched` of the customer's words appear in its
    name AND those words cover at least `min_query_coverage` of the query — this keeps
    a bare ingredient/category word ("pollo") from being treated as naming a recipe.

    Results are sorted best-first (more matched words, then a more complete name
    match) and carry the same extra keys as search_recipes() so they render with
    full ingredients and steps downstream.
    """
    q_words = _words(query)
    if not q_words:
        return []

    # A one-word request ("albóndigas", "receta de albondigas") can still name a
    # dish. Requiring two matched words made those unanswerable even though the
    # recipes exist. Allow a single word when it is a dish word rather than a
    # pantry staple — decided from the data: a term listed as an ingredient by
    # several recipes is an ingredient, so "pollo" still routes to pantry search
    # while "albóndigas" is treated as a name.
    effective_min = min_matched
    if len(q_words) == 1:
        word = next(iter(q_words))
        effective_min = 2 if word in _common_ingredient_words() else 1

    scored: list[tuple] = []
    for recipe in RECIPES:
        name_words = _words(recipe["name"])
        if not name_words:
            continue

        matched = _name_overlap(q_words, name_words)
        n_matched = len(matched)
        q_cov = n_matched / len(q_words)
        if n_matched < effective_min or q_cov < min_query_coverage:
            continue

        name_cov = n_matched / len(name_words)
        result = {
            **recipe,
            "have_count": 0,
            "total_ingredients": len(recipe.get("ingredients_normalized") or []),
            "have_pct": 0.0,
            "missing": [],
            "name_match": round((n_matched + q_cov + name_cov) / 3, 3),
        }
        # Sort key: most matched words, then most complete name match, then query cover.
        scored.append(((n_matched, name_cov, q_cov), result))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [r for _, r in scored[:top_n]]


# ── 2. Theory search ───────────────────────────────────────────────────────────

def search_theory(
    question: str,
    *,
    pillar: Optional[str] = None,
    top_n: int = 5,
) -> list[dict]:
    """
    Find theory chunks relevant to a technique question.

    question: free-text Spanish question or keyword string
    pillar:   "sal" | "grasa" | "acido" | "calor" | "general" | None (all)

    Each result dict is the original chunk dict plus:
      score         — relevance score (topic hits count 2×, content hits 1×)
      matched_words — sorted list of words that triggered the match
    """
    q_words = _words(question)

    results: list[dict] = []
    for chunk in CHUNKS:
        if pillar and chunk["pillar"] != pillar:
            continue

        topic_hits   = q_words & _words(chunk["topic"])
        content_hits = q_words & _words(chunk["content"])

        score = len(topic_hits) * 2 + len(content_hits)
        if score == 0:
            continue

        results.append({
            **chunk,
            "score": score,
            "matched_words": sorted(topic_hits | content_hits),
        })

    results.sort(key=lambda r: -r["score"])
    return results[:top_n]


# ── 3. Question router ─────────────────────────────────────────────────────────

# All values are accent-normalised (match after _norm())
_RECIPE_KW: set[str] = {
    "tengo", "ingredientes", "receta", "recetas", "cocinar", "preparar",
    "hacer", "cocino", "puedo", "rapida", "rapido", "rapidas", "rapidos",
    "sopas", "caldo", "caldos", "ensalada", "ensaladas",
    "carne", "carnes", "huevo", "huevos", "grano", "granos",
    "vegetal", "vegetales",
}

_TECHNIQUE_KW: set[str] = {
    "como", "porque", "cuanto", "cuando", "diferencia", "sirve", "funciona",
    "explica", "tecnica", "tecnicas", "metodo", "sazonar", "salar", "marinar",
    "dorar", "freir", "hervir", "coccion", "temperatura", "reaccion", "sirven",
}

# Pillar keywords boost technique_score and set theory_hints["pillar"]
# Include common conjugated forms so "salo", "dora", "frie" etc. are detected.
_PILLAR_KW: dict[str, list[str]] = {
    "sal":   ["sal", "salar", "salo", "salas", "salando", "sale", "salé",
              "sazonar", "sazona", "sazonando", "salado", "salada", "sodio", "kosher"],
    "grasa": ["grasa", "grasas", "aceite", "mantequilla", "manteca", "graso", "grasa"],
    "acido": ["acido", "acidos", "acida", "vinagre", "limon", "citrico", "agrio",
              "marinar", "marina", "marinando", "marinado"],
    "calor": ["calor", "temperatura", "fuego", "hervir", "hierve", "hirviendo",
              "freir", "frie", "friendo", "dorar", "dora", "dorando", "dorado",
              "cocer", "cuece", "coccion", "cocinar", "cocina"],
}

# Category keywords boost recipe_score and set recipe_hints["category"]
_CATEGORY_KW: dict[str, str] = {
    "sopa":      "Caldos & Sopas",
    "sopas":     "Caldos & Sopas",
    "caldo":     "Caldos & Sopas",
    "caldos":    "Caldos & Sopas",
    "carne":     "Carnes & Aves",
    "carnes":    "Carnes & Aves",
    "pollo":     "Carnes & Aves",
    "ave":       "Carnes & Aves",
    "aves":      "Carnes & Aves",
    "vegetal":   "Vegetales",
    "vegetales": "Vegetales",
    "ensalada":  "Ensaladas",
    "ensaladas": "Ensaladas",
    "huevo":     "Huevos",
    "huevos":    "Huevos",
    "grano":     "Granos",
    "granos":    "Granos",
    "calor":     "el calor",
    "grasa":     "la grasa",
    "acido":     "los ácidos",
    "acidos":    "los ácidos",
}

# Dish-type / meal-type requests map to a GROUP of categories rather than one
# exact category. "plato fuerte", "comida principal", "proteína" → the book's
# hearty mains (Carnes & Aves, Huevos, Caldos & Sopas); "acompañamiento",
# "guarnición" → the sides. Matched as substrings against the accent-normalised
# question so multi-word phrases ("plato fuerte") are detected too.
# Kept in sync with the categories actually present in recipes.json. The
# imports added "Proteínas" and "Pescados", which are mains; leaving them out
# made "plato fuerte" miss 14 dishes. Soups are deliberately NOT mains here —
# with them included, a "plato fuerte" request came back mostly soup.
_MAIN_DISH_CATS: list[str] = ["Carnes & Aves", "Proteínas", "Pescados", "Huevos"]
_SIDE_DISH_CATS: list[str] = ["Vegetales", "Granos", "Ensaladas", "Bases y Técnicas"]
_SOUP_CATS: list[str] = ["Caldos & Sopas"]

_DISH_TYPE_KW: dict[str, list[str]] = {
    "plato fuerte":     _MAIN_DISH_CATS,
    "platos fuertes":   _MAIN_DISH_CATS,
    "plato principal":  _MAIN_DISH_CATS,
    "platos principales": _MAIN_DISH_CATS,
    "plato de fondo":   _MAIN_DISH_CATS,
    "comida principal": _MAIN_DISH_CATS,
    "comida fuerte":    _MAIN_DISH_CATS,
    "algo fuerte":      _MAIN_DISH_CATS,
    "algo principal":   _MAIN_DISH_CATS,
    "algo de comer":    _MAIN_DISH_CATS,
    "proteina":         _MAIN_DISH_CATS,
    "proteinas":        _MAIN_DISH_CATS,
    "acompanamiento":   _SIDE_DISH_CATS,
    "acompanamientos":  _SIDE_DISH_CATS,
    "guarnicion":       _SIDE_DISH_CATS,
    "guarniciones":     _SIDE_DISH_CATS,
    "sopa":             _SOUP_CATS,
    "sopas":            _SOUP_CATS,
    "caldo":            _SOUP_CATS,
    "algo caliente":    _SOUP_CATS,
    "pescado":          ["Pescados"],
    "pescados":         ["Pescados"],
    "mariscos":         ["Pescados"],
    "salsa":            ["Salsas y Aderezos"],
    "salsas":           ["Salsas y Aderezos"],
    "aderezo":          ["Salsas y Aderezos"],
    "desayuno":         ["Desayunos", "Huevos"],
    "desayunos":        ["Desayunos", "Huevos"],
}


def route_question(question: str) -> dict:
    """
    Classify a Spanish question as "recipe", "technique", or "both".

    Returns:
      {
        "type":          "recipe" | "technique" | "both",
        "recipe_hints":  {"category": str | None, "sort_by_time": bool, "max_time": int | None},
        "theory_hints":  {"pillar": str | None},
        "scores":        {"recipe": int, "technique": int},
      }

    recipe_hints["category"] — detected recipe category to filter on, or None
    recipe_hints["sort_by_time"] — True when the question asks for the fastest recipe
    recipe_hints["max_time"] — time ceiling in minutes ("tengo 30 minutos"), or None
    theory_hints["pillar"] — sal/grasa/acido/calor if pillar detected, else None
    """
    q_norm  = _norm(question)
    q_words = set(re.findall(r"[a-z]+", q_norm))  # no stopword filter here — "como" matters

    recipe_score    = len(q_words & _RECIPE_KW)
    technique_score = len(q_words & _TECHNIQUE_KW)

    # "tengo" is the strongest single recipe signal
    if "tengo" in q_words:
        recipe_score += 3

    # Pillar keywords → strong technique signal
    detected_pillar: Optional[str] = None
    for pillar, kws in _PILLAR_KW.items():
        if any(kw in q_words for kw in kws):
            detected_pillar = pillar
            technique_score += 2
            break

    # Dish-type / meal-type requests ("plato fuerte", "proteína", "acompañamiento")
    # express intent more clearly than a bare ingredient word, so check them first
    # and map to the matching GROUP of categories.
    detected_category: Optional[str | list[str]] = None
    for phrase, cats in _DISH_TYPE_KW.items():
        if phrase in q_norm:
            detected_category = cats
            recipe_score += 1
            break

    # Single-word category keywords (sopa, carne, ensalada…) → category hint.
    if detected_category is None:
        for kw, cat in _CATEGORY_KW.items():
            if kw in q_words:
                detected_category = cat
                recipe_score += 1
                break

    # Time limit ("tengo 30 minutos") → recipe signal + ceiling on total time
    max_time = detect_max_time(question)
    if max_time is not None:
        recipe_score += 2

    # "más rápida/o" or "tiempo" → recipe + time-sort flag
    sort_by_time = bool(
        re.search(r"\bmas\s+rapida|\bmas\s+rapido|\brapida\b|\brapido\b|\btiempo\b|\bminutos\b", q_norm)
    )
    if sort_by_time:
        recipe_score += 1

    # Decide type
    if recipe_score > 0 and technique_score == 0:
        qtype = "recipe"
    elif technique_score > 0 and recipe_score == 0:
        qtype = "technique"
    else:
        # Both signals present — or neither (cast wide net)
        qtype = "both"

    return {
        "type":         qtype,
        "recipe_hints": {
            "category":     detected_category,
            "sort_by_time": sort_by_time or max_time is not None,
            "max_time":     max_time,
        },
        "theory_hints": {"pillar": detected_pillar},
        "scores":       {"recipe": recipe_score, "technique": technique_score},
    }


# ── Interactive demo ───────────────────────────────────────────────────────────

# A part is a time phrase, not an ingredient, if it mentions minutes/hours
_TIME_PART_RE = re.compile(r"\d|\bminut|\bhora|\bmedia\b|\bmin\b")


def _extract_listed_ingredients(text: str) -> list[str]:
    """Heuristic: extract 'tengo X, Y y Z' or 'con X, Y e Z' from a question.

    Time phrases ("30 minutos", "una hora") are NOT ingredients and are dropped.
    """
    q_norm = _norm(text)
    m = re.search(r"(?:tengo|con)\s+([\w\s,]+?)(?:\s*[.?]|$)", q_norm)
    if m:
        raw = m.group(1)
        parts = re.split(r",\s*|\s+y\s+|\s+e\s+", raw)
        return [
            p.strip() for p in parts
            if p.strip() and len(p.strip()) > 1 and not _TIME_PART_RE.search(p)
        ]
    return []


def _demo(question: str) -> None:
    SEP = "─" * 64
    print(f"\n{SEP}")
    print(f"  PREGUNTA : {question}")
    print(SEP)

    route = route_question(question)
    s = route["scores"]
    print(f"  RUTA     : {route['type'].upper()}"
          f"  (receta={s['recipe']}, técnica={s['technique']})")

    if route["type"] in ("recipe", "both"):
        h    = route["recipe_hints"]
        ings = _extract_listed_ingredients(question)
        if ings:
            hits = search_recipes(ings, category=h["category"], sort_by_time=h["sort_by_time"],
                                  max_time_minutes=h["max_time"])
        else:
            # No explicit ingredient list — show all (category-filtered) recipes
            # sorted by time or by name; coverage filtering doesn't apply.
            hits = search_recipes([], category=h["category"], sort_by_time=h["sort_by_time"],
                                  max_time_minutes=h["max_time"], min_coverage=0.0)
        cat_tag  = f" [cat: {h['category']}]" if h["category"] else ""
        time_tag = " [↑ tiempo]" if h["sort_by_time"] else ""
        max_tag  = f" [≤{h['max_time']} min]" if h["max_time"] else ""
        print(f"\n  RECETAS{cat_tag}{time_tag}{max_tag} — {len(hits)} resultado(s):")
        for r in hits:
            miss = ", ".join(r["missing"][:4]) if r["missing"] else "ninguno"
            print(f"    {r['have_pct']*100:3.0f}%  {r['name']}"
                  f"  ({r['total_time_minutes']} min)"
                  f"  faltan: {miss}")

    if route["type"] in ("technique", "both"):
        h    = route["theory_hints"]
        hits = search_theory(question, pillar=h["pillar"])
        pil_tag = f" [pilar: {h['pillar']}]" if h["pillar"] else ""
        print(f"\n  TEORÍA{pil_tag} — {len(hits)} resultado(s):")
        for r in hits:
            snippet = r["content"][:110].replace("\n", " ")
            print(f"    [{r['score']:2d}] [{r['pillar']:6s}]  {r['topic']}")
            print(f"          «{snippet}…»")


_EXAMPLES = [
    "Tengo pollo, cebolla, zanahoria, apio y laurel. ¿Qué puedo cocinar?",
    "¿Cuál es la receta más rápida de huevos?",
    "¿Cuándo debo agregar la sal al cocinar?",
    "¿Por qué es importante la grasa en la cocina?",
    "Tengo tomates, lechuga y vinagre. ¿Qué ensalada puedo hacer?",
    "¿Cómo funciona el ácido para marinar carnes?",
]

if __name__ == "__main__":
    import sys

    # Ensure UTF-8 output on Windows terminals
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) > 1:
        _demo(" ".join(sys.argv[1:]))
    else:
        for q in _EXAMPLES:
            _demo(q)

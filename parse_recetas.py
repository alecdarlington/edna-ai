"""Geometry-aware parsing of Edna's "Receta - <name>" PDFs (no API calls).

Guia-Meal-Planning and Recetario Proteínas share a layout that defeats
order-based parsing: the heading blocks are emitted *after* the content they
label, so in reading order "Ingredientes" appears below its own ingredient list
and "Procedimiento" below its steps. Everything is one font size, with no
bullets and no numbering, so size/boldness/markers carry no signal either.

The page is single-column though, so sorting lines by their y coordinate
restores the true order:

    y= 66  Receta - Frijoles de lata "mejorados"   <- title (22pt)
    y=119  Ingredientes                            <- heading, emitted last
    y=152  Rinde 1 ½ taza aproximadamente          <- servings
    y=200  2 cucharadas de aceite de oliva ...     <- one ingredient per line
    y=316  Procedimiento
    y=350  <paragraph>                             <- one step per block

Blocks are kept so each step paragraph stays whole after y-sorting.

Usage:
  python parse_recetas.py "Guia-Meal-Planning-EdnaCochez-2025V4.pdf"
"""

import re
import sys

import fitz  # PyMuPDF

from parse_guias import parse_time, strip_accents

# A title is much larger than the 10–12pt body text.
TITLE_MIN_SIZE = 15.0

TITLE_PREFIX_RE = re.compile(r"^(?:Receta|T[eé]cnica|Bonus)\s*[-–—:]\s*(.+)$",
                             re.IGNORECASE)
ING_HEAD_RE = re.compile(r"^Ingredientes\s*:?\s*$", re.IGNORECASE)
# Suffixes allowed: several recipes head their steps "Procedimiento de Salsa",
# which an anchored pattern misses — leaving the recipe with zero steps even
# though they sit right there on the same page. Length-capped so prose that
# happens to begin with the word is not mistaken for a heading.
PROC_HEAD_RE = re.compile(r"^(?:Procedimiento|Preparaci[oó]n)\b.{0,36}$", re.IGNORECASE)
# "Hace ½ taza" is a yield line like Rinde/Sirve; without it the phrase lands in
# the ingredient list.
SERV_RE = re.compile(r"^(?:Rinde|Sirve|Porciones|Hace)\b\s*:?\s*(.+)$", re.IGNORECASE)
TIME_RE = re.compile(r"^(?:Tiempo|Tiempo total|Listo en)\b\s*:?\s*(.+)$", re.IGNORECASE)
NOTE_RE = re.compile(r"^(?:NOTA|Nota|Notas|Tip|Prep Tip|M[eé]todo)\b", re.IGNORECASE)

# Page furniture to drop: running headers, page numbers, footers.
CHROME_RE = re.compile(
    r"^(?:SEMANA\b.*|D[IÍ]A\b\s*\d+|\d{1,3}|P[aá]gina\s*\d+|"
    r".*ednacochez\.com.*|.*Cocina Bajo Control.*)$",
    re.IGNORECASE,
)


def load_lines(path: str) -> list[dict]:
    """Flatten the PDF into y-ordered logical lines, tagged with block identity.

    Sorting by (page, y, x) is the whole trick: it undoes the scrambled block
    order. Block ids are retained so step paragraphs can be rejoined.
    """
    doc = fitz.open(path)
    out: list[dict] = []
    for pno, page in enumerate(doc, start=1):
        rows = []
        for bno, block in enumerate(page.get_text("dict")["blocks"]):
            for line in block.get("lines", []):
                spans = line["spans"]
                text = "".join(s["text"] for s in spans)
                text = text.replace("​", "").replace("\xa0", " ").strip()
                if not text or CHROME_RE.match(text):
                    continue
                size = max((s["size"] for s in spans if s["text"].strip()), default=0)
                bold = any("bold" in s["font"].lower() for s in spans)
                x0, y0 = line["bbox"][0], line["bbox"][1]
                rows.append({"text": text, "size": size, "bold": bold,
                             "page": pno, "block": (pno, bno),
                             "x": x0, "y": y0})
        rows.sort(key=lambda r: (round(r["y"], 1), r["x"]))
        out.extend(rows)
    return out


def is_title(item: dict) -> bool:
    return item["size"] >= TITLE_MIN_SIZE


def title_text(text: str) -> str:
    """Strip the "Receta - " / "Técnica - " prefix from a title."""
    m = TITLE_PREFIX_RE.match(text)
    t = (m.group(1) if m else text).strip()
    # Only unwrap quotes that enclose the whole title; a blanket strip turns
    # 'Frijoles de lata "mejorados"' into 'Frijoles de lata "mejorados'.
    if len(t) > 1 and t[0] in "“\"" and t[-1] in "”\"":
        t = t[1:-1].strip()
    return t


# Coarse dish-type inference. These books are organised by week, not by dish, so
# there is no section heading to read a category from — and leaving it None
# breaks search.py's category filter. Keys are checked in order.
# Order matters. "Pollo en salsa cremosa" is a chicken dish, not a sauce, so the
# protein rules are checked before the sauce rules.
CATEGORY_RULES = [
    ("Sopas", ("sopa", "caldo", "crema de", "consome")),
    ("Ensaladas", ("ensalada", "chopped salad", "tabouleh", "coleslaw")),
    ("Desayunos", ("huevo", "omelette", "avena", "pancake", "tostada", "frittata",
                   "scramble", "pudding", "smoothie", "batido")),
    ("Bases (Carbohidratos)", ("arroz", "quinoa", "pasta", "camote", "yuca",
                               "platano", "tortilla", "pan ", "papa", "cuscus")),
    ("Granos", ("lenteja", "frijol", "garbanzo", "menestra", "poroto", "legumbre")),
    ("Pescados", ("pescado", "salmon", "atun", "camaron")),
    ("Carnes & Aves", ("pollo", "carne", "res", "cerdo", "puerco", "pavo", "lomo",
                       "chuleta", "milanesa", "albondiga", "kofte", "chile con",
                       "ropa vieja", "costilla", "bistec")),
    ("Vegetales", ("brocoli", "vegetales", "berenjena", "habichuela", "esparrago",
                   "coliflor", "zucchini", "espinaca", "hongos", "champinon")),
    ("Salsas y Aderezos", ("salsa", "aderezo", "vinagreta", "adobo", "mezcla de especias",
                           "mantequilla compuesta", "pico de gallo", "chimichurri",
                           "pesto", "hummus", "guacamole")),
]
CATEGORY_FALLBACK = "Otros"


def infer_category(name: str, ingredients: list[str]) -> str:
    """Guess a dish-type category from the recipe name, then its ingredients."""
    hay = strip_accents(name or "")
    for cat, keys in CATEGORY_RULES:
        if any(k in hay for k in keys):
            return cat
    hay2 = strip_accents(" ".join(ingredients[:6]))
    for cat, keys in CATEGORY_RULES:
        if any(k in hay2 for k in keys):
            return cat
    return CATEGORY_FALLBACK


def _group_blocks(items: list[dict]) -> list[str]:
    """Join consecutive lines belonging to the same PDF block into paragraphs."""
    out: list[str] = []
    current_block = None
    for it in items:
        if it["block"] != current_block:
            out.append(it["text"])
            current_block = it["block"]
        else:
            out[-1] = f"{out[-1]} {it['text']}"
    return [re.sub(r"\s+", " ", s).strip() for s in out if s.strip()]


def merge_titles(items: list[dict]) -> list[dict]:
    """Collapse a title that wraps over several lines into one item.

    "Ensalada de carne a la plancha (steak salad)" is set across two lines; left
    separate, the second line starts a phantom recipe that then swallows the
    real one's steps.
    """
    out: list[dict] = []
    for it in items:
        if out and is_title(it) and is_title(out[-1]) \
                and it["page"] == out[-1]["page"] \
                and 0 <= it["y"] - out[-1]["y"] <= 3.2 * it["size"]:
            merged = dict(out[-1])
            merged["text"] = f"{out[-1]['text']} {it['text']}".strip()
            out[-1] = merged
            continue
        out.append(it)
    return out


def parse(path: str) -> list[dict]:
    """Extract recipes, one per title that owns an Ingredientes or Procedimiento."""
    items = merge_titles(load_lines(path))

    # Segment the document at title lines.
    starts = [n for n, it in enumerate(items) if is_title(it)]
    recipes: list[dict] = []

    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(items)
        body = items[start + 1:end]
        name = title_text(items[start]["text"])

        ing_at = next((k for k, x in enumerate(body)
                       if ING_HEAD_RE.match(x["text"])), None)
        proc_at = next((k for k, x in enumerate(body)
                        if PROC_HEAD_RE.match(x["text"])), None)
        if ing_at is None and proc_at is None:
            continue                      # prose section, not a recipe

        servings = minutes = None
        notes: list[str] = []

        # Ingredients: between the heading and the next heading.
        ing_items: list[dict] = []
        if ing_at is not None:
            stop = proc_at if (proc_at is not None and proc_at > ing_at) else len(body)
            for x in body[ing_at + 1:stop]:
                t = x["text"]
                sm = SERV_RE.match(t)
                if sm:
                    servings = servings or sm.group(1).strip().rstrip(".")
                    continue
                tm = TIME_RE.match(t)
                if tm:
                    minutes = minutes or parse_time(tm.group(1))
                    continue
                if NOTE_RE.match(t):
                    notes.append(t)
                    continue
                ing_items.append(x)

        # Anything above the Ingredientes heading is title matter: Rinde/Sirve
        # can also sit there depending on the page.
        head_zone = body[:ing_at] if ing_at is not None else body[:proc_at or 0]
        for x in head_zone:
            sm = SERV_RE.match(x["text"])
            if sm and not servings:
                servings = sm.group(1).strip().rstrip(".")
            tm = TIME_RE.match(x["text"])
            if tm and not minutes:
                minutes = parse_time(tm.group(1))

        # Steps: everything after the Procedimiento heading, by paragraph.
        step_items: list[dict] = []
        if proc_at is not None:
            for x in body[proc_at + 1:]:
                if NOTE_RE.match(x["text"]):
                    notes.append(x["text"])
                    continue
                step_items.append(x)

        # One ingredient per line — the whole list is a single PDF block, so
        # block-grouping would fuse them into one string. Steps are the opposite:
        # each paragraph is a block whose lines must be rejoined.
        ingredients = [re.sub(r"\s+", " ", x["text"]).strip() for x in ing_items
                       if x["text"].strip()]
        steps = _group_blocks(step_items)

        # A title with neither ingredients nor steps is a section head, not food.
        if not ingredients and not steps:
            continue
        # Reject non-recipe pages that happen to contain the word "ingredientes"
        # in running text — the equipment list has "Tazones pequeños para medir
        # ingredientes" wrapped so that "ingredientes" lands on its own line.
        if not steps and not servings:
            continue

        recipes.append({
            "name": name,
            "category": infer_category(name, ingredients),
            "servings": servings,
            "ingredients": ingredients,
            "steps": steps,
            "total_time_minutes": minutes,
            "notes": notes,
            "page": items[start]["page"],
            "source": path,
        })

    return stitch_spreads(recipes)


def stitch_spreads(recipes: list[dict]) -> list[dict]:
    """Rejoin a recipe printed across two pages.

    The title repeats on the continuation page, so segmentation yields one entry
    holding the ingredients and a second holding the steps ("Ropa Vieja al estilo
    cubano" as 28 ingredients / 0 steps, then 0 / 4). Merge them when the names
    line up and the pages are adjacent.
    """
    out: list[dict] = []
    for r in recipes:
        prev = out[-1] if out else None
        if prev and 0 <= r["page"] - prev["page"] <= 2:
            a, b = strip_accents(prev["name"] or ""), strip_accents(r["name"] or "")
            related = a == b or a.endswith(b) or b.endswith(a) or a in b or b in a
            complementary = (
                (not r["ingredients"] and not prev["steps"])
                or (not r["steps"] and not prev["ingredients"])
            )
            if related and complementary:
                prev["ingredients"] = prev["ingredients"] or r["ingredients"]
                prev["steps"] = prev["steps"] or r["steps"]
                prev["servings"] = prev["servings"] or r["servings"]
                prev["total_time_minutes"] = (prev["total_time_minutes"]
                                              or r["total_time_minutes"])
                prev["notes"] = (prev["notes"] or []) + (r["notes"] or [])
                # The longer title is usually the complete one.
                if len(r["name"] or "") > len(prev["name"] or ""):
                    prev["name"] = r["name"]
                prev["category"] = infer_category(prev["name"], prev["ingredients"])
                continue
        out.append(r)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("Uso: python parse_recetas.py <archivo.pdf>")
        sys.exit(1)

    rs = parse(sys.argv[1])
    print(f"TOTAL recipes: {len(rs)}\n")
    for n, r in enumerate(rs):
        print(f"[{n:03d}] p{r['page']:<4} {str(r['name'])[:46]:<48} "
              f"serv={str(r['servings'])[:18]:<20} t={str(r['total_time_minutes']):<5} "
              f"ing={len(r['ingredients']):<3} steps={len(r['steps'])}")
    print(f"\nno-name={sum(1 for r in rs if not r['name'])} "
          f"no-ing={sum(1 for r in rs if not r['ingredients'])} "
          f"no-steps={sum(1 for r in rs if not r['steps'])} "
          f"no-serv={sum(1 for r in rs if not r['servings'])}")

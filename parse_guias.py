"""Deterministic parsing of Edna's newer guide PDFs (no API calls).

These files are laid out differently from the Conquista la Cocina workbook that
`parse_core.py` handles:

  Pollos y Aves                     <- 17pt Georgia-Bold section heading
  Pechuga de Pollo a la Plancha     <- 17pt Georgia-Bold recipe title
  <italic intro paragraph>
  RINDE: 2 PORCIONES · TIEMPO: 20 MINUTOS · VIDEO DISPONIBLE EN HOTMART
  INGREDIENTES                      <- uppercase heading, not "Ingredientes:"
  •  ...
  PREPARACIÓN                       <- uppercase, replaces "Procedimiento:"
  1. ...
  Nota: ...

So recipes anchor on the INGREDIENTES/PREPARACIÓN pair, the title is the nearest
preceding heading-sized line, and category/title are told apart by the fact that
a section heading is immediately followed by another heading-sized line.

The RINDE/TIEMPO line gives servings and total time deterministically, so those
two fields need no model call for this format.

Usage:
  python parse_guias.py "Mi Guia de Cocina Saludable Sistema 3x5 - Edna Cochez 2026.pdf"
"""

import re
import sys
import unicodedata

import fitz  # PyMuPDF

from parse_core import clean_line, parse_ingredients, parse_steps

# Heading-sized lines (recipe titles and section headings share this size).
# Titles run 17pt in the early sections and drop to 14pt later in the book, so
# the floor sits below both and boldness carries the rest of the signal.
# 13pt is used for the Huevos Rancheros / Huevos Turcos titles, so the floor
# sits just below that; body text never exceeds 11pt.
TITLE_MIN_SIZE = 12.5

# The index lists recipes with ● while ingredient lists use •, which makes the
# index trivially separable and gives us the book's own list of recipe names.
INDEX_BULLET_RE = re.compile(r"^●\s*(.+)$")
INDEX_HEADING_RE = re.compile(r"^INDICE\b", re.IGNORECASE)

# Section headings that are structural, never recipes.
NON_RECIPE_TITLES = {
    "indice de recetas", "indice", "menus de muestra", "tu plato",
    "como funciona el sistema", "como se ve en la practica",
    "los 3 componentes del plato", "la despensa", "despensa",
    "equivalencias", "notas finales", "introduccion",
}

# Both step headings, so this parser works on the older marker too.
PROC_RE = re.compile(r"^(?:Procedimiento|Preparaci[oó]n)\b\s*:?\s*$", re.IGNORECASE)
# Many recipes skip a plain "INGREDIENTES" and head each component group
# instead — PARA LA SALSA, PARA LOS VEGETALES, PARA EL SALMÓN. Those anchor a
# recipe just as well, and several groups belong to one recipe.
# "Ingredientes\b.*" also covers "INGREDIENTES BASE" / "INGREDIENTES PARA ...".
ING_RE = re.compile(
    r"^(?:Ingredientes\b.*|Para\s+(?:la|el|los|las)\s+\S.*|Para\s+servir|"
    r"Para\s+armar|Para\s+acompa[nñ]ar)\s*:?\s*$",
    re.IGNORECASE,
)
# Only a short bold line counts as a heading, so prose beginning "Para la ..."
# is not mistaken for one.
HEADING_MAX_LEN = 48
# Searched, not anchored: the metadata line often leads with something else,
# e.g. "TÉCNICA BASE DEL OMELETTE · RINDE: 1 PORCIÓN · TIEMPO: 5 MINUTOS".
META_RE = re.compile(r"\b(?:RINDE|SIRVE|PORCIONES|TIEMPO)\s*:", re.IGNORECASE)
FOOTER_RE = re.compile(r"ednacochez\.com|Cocina Bajo Control", re.IGNORECASE)
NOTE_RE = re.compile(r"^(Nota|Notas|Tip|Variaci[oó]n)\b", re.IGNORECASE)

SERV_PART_RE = re.compile(r"^(?:RINDE|SIRVE|PORCIONES)\s*:?\s*(.+)$", re.IGNORECASE)
TIME_PART_RE = re.compile(r"^TIEMPO\s*:?\s*(.+)$", re.IGNORECASE)


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


def parse_time(phrase: str) -> int | None:
    """Turn 'TIEMPO: 1 HORA 20 MINUTOS' or '20 minutos' into total minutes."""
    p = strip_accents(phrase)
    total = 0
    # The trailing s? matters: "20 MINUTOS" is the common form, and a bare \b
    # after "minuto" cannot match it.
    hours = re.search(r"(\d+)\s*(?:horas?|hrs?|h)\b", p)
    if hours:
        total += int(hours.group(1)) * 60
    mins = re.search(r"(\d+)\s*(?:minutos?|mins?)\b", p)
    if mins:
        total += int(mins.group(1))
    if not total:
        # Bare number with no unit, e.g. "TIEMPO: 25"
        bare = re.fullmatch(r"\s*(\d{1,3})\s*", p)
        if bare:
            total = int(bare.group(1))
    return total or None


def parse_meta(line: str) -> tuple[str | None, int | None]:
    """Read servings and total minutes out of a RINDE/TIEMPO metadata line."""
    servings = minutes = None
    for part in re.split(r"\s*[·|]\s*", line):
        part = part.strip()
        if not part:
            continue
        sm = SERV_PART_RE.match(part)
        if sm and servings is None:
            servings = sm.group(1).strip().rstrip(".").lower()
            continue
        tm = TIME_PART_RE.match(part)
        if tm and minutes is None:
            minutes = parse_time(tm.group(1))
    return servings, minutes


def load_lines(path: str) -> list[dict]:
    """Flatten the PDF into logical lines tagged with their largest font size."""
    doc = fitz.open(path)
    out = []
    for pno, page in enumerate(doc, start=1):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line["spans"]
                text = clean_line("".join(s["text"] for s in spans))
                if not text or FOOTER_RE.search(text):
                    continue
                size = max((s["size"] for s in spans if s["text"].strip()), default=0)
                bold = any("bold" in s["font"].lower() for s in spans)
                out.append({"text": text, "size": size, "bold": bold, "page": pno})
    return out


def is_title(item: dict) -> bool:
    return item["size"] >= TITLE_MIN_SIZE and bool(item["text"])


# Heading families. Membership alone is not enough — PARA ARMAR heads a bullet
# list in one recipe and a numbered list in another — so the lines that FOLLOW a
# heading decide its role. That single rule covers the whole book's vocabulary.
ING_HEAD_RE = re.compile(
    r"^(?:Ingredientes\b.*|Para\s+(?:la|el|los|las|servir|armar|acompa[nñ]ar)\b.*|"
    r"Versi[oó]n\b.*|Toppings\b.*)$",
    re.IGNORECASE,
)
PROC_HEAD_RE = re.compile(
    r"^(?:Preparaci[oó]n\b.*|Procedimiento\b.*|T[eé]cnica\b.*|Para\s+armar\b.*|"
    r"Una\s+forma\s+de\s+servirla\b.*)$",
    re.IGNORECASE,
)
BULLET_START_RE = re.compile(r"^[•●○▪◦]")
NUM_START_RE = re.compile(r"^\d+\.")
# A numbered sub-recipe inside a grouped page, e.g. "1. Sofrito Panameño".
SUB_RECIPE_RE = re.compile(r"^\d+\.\s+([A-ZÁÉÍÓÚÑ][^.]{2,60})$")
# Variant labels that mean "same dish, different execution".
VARIANT_RE = re.compile(r"^(?:Versi[oó]n|Preparaci[oó]n)\b\s*(?:\d+)?\s*[—–-]?\s*(.*)$",
                        re.IGNORECASE)


def _follows(items: list[dict], i: int) -> str:
    """Whether the line after index i starts a bullet list or a numbered list."""
    if i + 1 >= len(items):
        return "other"
    nxt = items[i + 1]["text"]
    if BULLET_START_RE.match(nxt):
        return "bullet"
    if NUM_START_RE.match(nxt):
        return "num"
    return "other"


def heading_role(items: list[dict], i: int) -> str | None:
    """Classify a line as an 'ing' or 'proc' group heading, or None."""
    it = items[i]
    t = it["text"]
    if not it["bold"] or len(t) > HEADING_MAX_LEN or is_title(it):
        return None
    kind = _follows(items, i)
    if PROC_HEAD_RE.match(t) and kind == "num":
        return "proc"
    if ING_HEAD_RE.match(t) and kind == "bullet":
        return "ing"
    # A lone "PREPARACIÓN"-family heading with prose under it is still steps.
    if PROC_HEAD_RE.match(t) and kind == "other":
        return "proc"
    return None


def is_ing_heading(item: dict) -> bool:
    """Kept for callers that only have the line: shape test, no lookahead."""
    t = item["text"]
    return (
        len(t) <= HEADING_MAX_LEN
        and item["bold"]
        and not is_title(item)
        and bool(ING_HEAD_RE.match(t))
    )


def is_proc_heading(item: dict) -> bool:
    return item["bold"] and bool(PROC_HEAD_RE.match(item["text"]))


def key(text: str | None) -> str:
    """Normalise a title for comparison: no accents, no punctuation, one space."""
    if not text:
        return ""
    t = strip_accents(text)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def similar(a: str, b: str) -> float:
    """Similarity of two normalised titles, by sequence and by shared words."""
    import difflib

    ka, kb = key(a), key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    seq = difflib.SequenceMatcher(None, ka, kb).ratio()
    ta, tb = set(ka.split()), set(kb.split())
    tok = len(ta & tb) / max(len(ta), len(tb))
    return max(seq, tok)


def variant_label(label: str) -> str | None:
    """The distinguishing part of a VERSIÓN/PREPARACIÓN — X heading, if any."""
    m = VARIANT_RE.match(label)
    if not m:
        return None
    tail = m.group(1).strip(" —–-:")
    # A bare "PREPARACIÓN" or "VERSIÓN" carries no distinction.
    if not tail or strip_accents(tail) in {"base", "de la salsa"}:
        return None
    return tail


def method_name(parent: str | None, label: str, idx: int, total: int) -> str:
    """Name one of several cooking methods for the same ingredients.

    "Yuca hervida o al vapor" with methods HERVIDA / AL VAPOR should become
    "Yuca hervida" and "Yuca al vapor" — appending the label instead gives two
    names that normalise identically, and the dedupe guard then drops one.
    """
    if not parent:
        return label.title()
    parts = [p.strip() for p in re.split(r"\s+o\s+", parent) if p.strip()]
    if len(parts) == total:
        head = parts[0].split()[0]
        chosen = parts[idx]
        if strip_accents(chosen).startswith(strip_accents(head)):
            return chosen
        return f"{head} {chosen}"
    return f"{parent} ({label.lower()})"


def _assemble(name, category, servings, minutes, ing_lines, step_lines,
              labels, page, path) -> dict:
    """Turn raw line groups into one recipe record."""
    ingredients, ing_notes = parse_ingredients(ing_lines)
    steps, step_notes = parse_steps(step_lines)

    notes, kept = list(ing_notes) + list(step_notes), []
    for s in steps:
        if NOTE_RE.match(s):
            notes.append(s)
        else:
            kept.append(s)
    if len(labels) > 1:
        notes.insert(0, f"Grupos: {'; '.join(labels)}")

    return {
        "name": name,
        "category": category,
        "servings": servings,
        "ingredients": ingredients,
        "steps": kept,
        "total_time_minutes": minutes,
        "notes": [n for n in notes if n],
        "page": page,
        "source": path,
    }


def build_recipes(name, category, servings, minutes, ing_groups, step_groups,
                  page, path) -> list[dict]:
    """One group set becomes one recipe — or several, when it holds variants.

    The book presents some dishes as a single entry with two executions
    (VERSIÓN 1 / VERSIÓN 2, PREPARACIÓN — HERVIDA / AL VAPOR) while its own
    index lists them separately. Splitting matches the index, and matches how
    the workbook's variants were kept distinct.
    """
    ing_variants = [(variant_label(l), l, b) for l, b in ing_groups]
    step_variants = [(variant_label(l), l, b) for l, b in step_groups]

    named_ing = [v for v in ing_variants if v[0]]
    named_step = [v for v in step_variants if v[0]]

    # Case 1: variant ingredient groups, each with a matching step group.
    if len(named_ing) > 1:
        out = []
        shared_steps = [ln for v, l, b in step_variants if not v for ln in b]
        def vnum(s: str) -> str | None:
            m = re.search(r"\d+", s or "")
            return m.group(0) if m else None

        for vlabel, label, body in named_ing:
            # "VERSIÓN 1 — CON VEGETALES ROSTIZADOS" pairs with
            # "PREPARACIÓN — VERSIÓN 1": the shared signal is the number, not
            # the wording, so match on that first and fall back to text.
            n = vnum(label)
            match = next(
                (b for v, l, b in step_variants
                 if v and n and vnum(l) == n),
                None,
            )
            if match is None:
                match = next(
                    (b for v, l, b in step_variants
                     if v and (similar(v, vlabel) >= 0.6 or key(vlabel) in key(l))),
                    None,
                )
            out.append(_assemble(
                f"{name} — {vlabel}" if name else vlabel,
                category, servings, minutes, body,
                match if match is not None else shared_steps,
                [label], page, path,
            ))
        return out

    # Case 2: one ingredient list, several named methods (Camote, Yuca).
    if len(named_step) > 1:
        shared = [ln for l, b in ing_groups for ln in b]
        labels = [l for l, _ in ing_groups]
        return [
            _assemble(method_name(name, vlabel, n, len(named_step)), category,
                      servings, minutes, shared, body, labels, page, path)
            for n, (vlabel, label, body) in enumerate(named_step)
        ]

    # Default: a single recipe built from every group.
    return [_assemble(
        name, category, servings, minutes,
        [ln for _, b in ing_groups for ln in b],
        [ln for _, b in step_groups for ln in b],
        [l for l, _ in ing_groups], page, path,
    )]


def tidy_variant_name(name: str | None, index_names: list[str]) -> str | None:
    """Replace a machine-built variant name with the book's own index wording.

    Splitting produces "Quinoa con Vegetales Rostizados o Champiñones y Arúgula
    — CON VEGETALES ROSTIZADOS"; the index simply calls it "Quinoa con vegetales
    rostizados". Pick the index entry that is contained in the built name AND
    shares a word with the variant label, so the two versions don't collapse to
    the same entry.
    """
    if not name or " — " not in name:
        return name
    parent, _, label = name.rpartition(" — ")
    all_words = set(key(name).split())
    label_words = set(key(label).split()) - {"con", "de", "la", "el", "los", "las"}

    best = None
    for entry in index_names:
        ew = set(key(entry).split())
        if ew and ew <= all_words and (not label_words or ew & label_words):
            if best is None or len(ew) > len(set(key(best).split())):
                best = entry
    return best or name


def load_index(items: list[dict]) -> tuple[list[str], list[str]]:
    """Read the book's own index: (recipe names, section/category names).

    The index gives ground truth for both, which is far more reliable than
    guessing from font size — titles and section headings are set identically.
    """
    pages = {it["page"] for it in items if INDEX_BULLET_RE.match(it["text"])}
    if not pages:
        return [], []
    lo, hi = min(pages), max(pages)

    names, cats = [], []
    for it in items:
        if not (lo <= it["page"] <= hi):
            continue
        m = INDEX_BULLET_RE.match(it["text"])
        if m:
            names.append(m.group(1).strip())
        elif is_title(it) and not INDEX_HEADING_RE.match(it["text"]):
            cats.append(it["text"].strip())
    return names, cats


def match_index(text: str, index: list[str], floor: float = 0.80) -> str | None:
    """Return the index entry this title corresponds to, if any."""
    best, score = None, 0.0
    for entry in index:
        s = similar(text, entry)
        if s > score:
            best, score = entry, s
    return best if score >= floor else None


def match_section(text: str, cats: list[str]) -> str | None:
    """Match a big section-divider line to an index category.

    Dividers are often shortened: the index says "BASES (CARBOHIDRATOS)" while
    the divider page just says "BASES". Similarity scores that at 0.5, so fall
    back to token containment — the divider's words being a subset of the
    category's is strong enough evidence on its own.
    """
    exact = match_index(text, cats, 0.90)
    if exact:
        return exact
    tw = set(key(text).split())
    if not tw:
        return None
    for entry in cats:
        ew = set(key(entry).split())
        if ew and tw <= ew:
            return entry
    return None


def parse(path: str) -> list[dict]:
    """Extract recipes. Each needs an INGREDIENTES heading to count as one."""
    items = load_lines(path)
    index_names, index_cats = load_index(items)
    index_pages = {it["page"] for it in items if INDEX_BULLET_RE.match(it["text"])}

    recipes = []
    category = None
    i = 0
    pending_title = None
    while i < len(items):
        it = items[i]
        text = it["text"]

        # Skip the index itself; its bullets are not ingredients.
        if it["page"] in index_pages:
            i += 1
            continue

        if is_title(it):
            # A title may wrap onto the next heading-sized line. Prefer the
            # longer join when that is what actually matches the index.
            joined, span = text, 1
            if i + 1 < len(items) and is_title(items[i + 1]):
                nxt = items[i + 1]["text"]
                cand = f"{text} {nxt}".strip()
                # Join when the continuation is not a title in its own right —
                # a fragment like "Avellanada)" closing a wrapped name — or when
                # the joined form matches the index better than the first line.
                orphan = (
                    len(nxt) <= 28
                    and not match_index(nxt, index_names, 0.85)
                    and not match_index(nxt, index_cats, 0.90)
                )
                better = (
                    match_index(cand, index_names, 0.80)
                    and not match_index(text, index_cats, 0.90)
                )
                if orphan or better:
                    joined, span = cand, 2

            section = match_section(joined, index_cats)
            if section or strip_accents(joined) in NON_RECIPE_TITLES:
                # Store the index's full wording, not the divider's short form.
                category = section or joined
                pending_title = None
            else:
                pending_title = match_index(joined, index_names) or joined
            i += span
            continue

        # A recipe starts at its first ingredient group, or straight at
        # PREPARACIÓN for technique recipes that list no ingredients at all
        # (e.g. Hojas Verdes Blanqueadas).
        # Numbered sub-recipes inside a grouped page: "1. Sofrito Panameño",
        # "2. Mirepoix (Francia) / Soffrito (Italia)". Their ingredients are
        # written inline in the prose, so steps carry the text and extract.py
        # pulls the ingredients out of it later.
        if it["bold"] and not is_title(it) and heading_role(items, i) is None \
                and SUB_RECIPE_RE.match(text):
            sub_name = SUB_RECIPE_RE.match(text).group(1).strip()
            j = i + 1
            body = []
            while j < len(items) and not is_title(items[j]) \
                    and heading_role(items, j) is None \
                    and not (items[j]["bold"]
                             and SUB_RECIPE_RE.match(items[j]["text"])):
                body.append(items[j]["text"])
                j += 1
            if body:
                recipes.append(_assemble(sub_name, category, None, None,
                                         [], body, [], it["page"], path))
            i = j
            continue

        role = heading_role(items, i)
        if role:
            servings = minutes = None
            # The RINDE/TIEMPO line sits just above the first heading.
            for back in range(i - 1, max(-1, i - 8), -1):
                if META_RE.search(items[back]["text"]):
                    servings, minutes = parse_meta(items[back]["text"])
                    break

            # Collect labelled groups, keeping them separate so a recipe with
            # VERSIÓN 1 / VERSIÓN 2 can be split afterwards. Groups are read in
            # document order until the next recipe title.
            ing_groups: list[tuple[str, list[str]]] = []
            step_groups: list[tuple[str, list[str]]] = []
            j = i
            while j < len(items):
                r = heading_role(items, j)
                if not r:
                    break
                label = items[j]["text"]
                j += 1
                body: list[str] = []
                while j < len(items) and not is_title(items[j]) \
                        and not heading_role(items, j):
                    body.append(items[j]["text"])
                    j += 1
                (ing_groups if r == "ing" else step_groups).append((label, body))

            built = build_recipes(pending_title, category, servings, minutes,
                                  ing_groups, step_groups, it["page"], path)
            # Adopt the index wording only if it keeps the variants distinct.
            # "Yuca hervida" and "Yuca al vapor" both match the single index
            # entry "Yuca hervida o al vapor"; renaming both would merge them.
            tidied = [tidy_variant_name(r["name"], index_names) for r in built]
            if len(set(tidied)) == len(tidied):
                for rec, new_name in zip(built, tidied):
                    rec["name"] = new_name
            recipes.extend(built)
            pending_title = None
            i = j
            continue

        i += 1

    return recipes


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("Uso: python parse_guias.py <archivo.pdf>")
        sys.exit(1)

    rs = parse(sys.argv[1])
    print(f"TOTAL recipes: {len(rs)}\n")
    for n, r in enumerate(rs):
        print(f"[{n:03d}] p{r['page']:<4} {str(r['category'])[:20]:<20} | "
              f"{str(r['name'])[:44]:<44} | serv={str(r['servings'])[:16]:<16} "
              f"t={str(r['total_time_minutes']):<5} ing={len(r['ingredients']):<3} "
              f"steps={len(r['steps'])}")
    missing = [r for r in rs if not r["name"]]
    print(f"\nno-name: {len(missing)}   no-ingredients: "
          f"{sum(1 for r in rs if not r['ingredients'])}   "
          f"no-steps: {sum(1 for r in rs if not r['steps'])}")

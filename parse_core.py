"""Core deterministic parsing of the Recetas PDF (no API calls).

The cookbook's running header "Conquista la Cocina: <category>" marks the
teaching category. Within a category there may be one main recipe or several
(variants/vinaigrettes). Each recipe is anchored on a "Procedimiento:" block;
its ingredients are the nearest preceding "Ingredientes:" group(s) and its
name is the title line(s) found by scanning upward past intro prose / "Rinde".
"""
import re
import fitz  # PyMuPDF

PDF_PATH = "Workbook Conquista La Cocina - Edna Cochez - Recetas (1).pdf"
ZWSP = "​"

HEADER_RE = re.compile(r"^Conquista la Cocina:\s*(.+?)\s*$")
BONUS_RE = re.compile(r"^Bonuses?\s*:\s*(.+)$", re.IGNORECASE)
FOOTER_RE = re.compile(r"Edna Cochez\s*-\s*Conquista la Cocina.*ednacochez\.com")
ING_RE = re.compile(r"^Ingredientes\b(.*?):?\s*$", re.IGNORECASE)
INLINE_ING_RE = re.compile(r"^(.*\S)\s+(Ingredientes\s*:?)\s*$", re.IGNORECASE)
PROC_RE = re.compile(r"^Procedimiento\b.*$", re.IGNORECASE)
SERV_RE = re.compile(r"^(?:Rinde|Sirve)\b[:\s]+(.*\S)\s*$", re.IGNORECASE)
STEP_RE = re.compile(r"^(\d+)\.\s*(.*)$")
BULLET_RE = re.compile(r"^[●○▪•◦]\s*(.*)$")  # ● ○ ▪ • ◦
SUBLABEL_RE = re.compile(
    r"^(Para servir|Para acompañar|Para armar|Nota|Notas|Variaci[oó]n|Variante|Opcional|Equipo|Implemento)\b",
    re.IGNORECASE,
)
# Lines that are NOT recipe titles (metadata / intro prose openers).
SKIP_TITLE_RE = re.compile(
    r"^(Total|Activo|Tiempo|Rendimiento|Cocinar|Cocci[oó]n|Reposo|Reposar|Marinar|"
    r"Enfriar|Hornear|Horneado|Equipo|Implemento|Para servir|Para acompañar|"
    r"Para armar|Para agregar|Nota|Notas|Opcional|Ideal|Esta|Este|Esto|Funciona|"
    r"Puedes|Guarda|Util[ií]za|Sirve|Rinde|Kufte|Kibbeh)\b", re.IGNORECASE)
# A detected "name" that is actually a serving/variation note -> merge upward.
NONRECIPE_NAME_RE = re.compile(
    r"^(Para servir|Para agregar|Variaciones)", re.IGNORECASE)
# Lines whose suffix IS the recipe name (variants).
NAME_PREFIX_RE = re.compile(
    r"^(?:Variaci[oó]n|Variante|Para hacer)\s*:?\s*(.+?):?\s*$", re.IGNORECASE)
CATEGORY_FIX = {"ensaladas": "Ensaladas"}
CONNECTORS = {"con", "de", "del", "y", "e", "o", "a", "al", "en", "la", "el",
              "los", "las", "para", "sin", "&", "que", "sobre"}


def clean_line(line: str) -> str:
    return line.replace(ZWSP, "").replace("\xa0", " ").strip()


def load_blocks():
    """Yield (category, [lines]) blocks, one per running-header / bonus section."""
    doc = fitz.open(PDF_PATH)
    blocks = []
    current = None

    def add(line):
        if current is not None:
            current[1].append(line)

    for page in doc:
        for raw in page.get_text().split("\n"):
            ln = clean_line(raw)
            if FOOTER_RE.search(ln):
                continue
            if not ln:
                if current is not None and (not current[1] or current[1][-1] != ""):
                    current[1].append("")
                continue
            m = HEADER_RE.match(ln)
            if m:
                cat = m.group(1).strip()
                current = [CATEGORY_FIX.get(cat.lower(), cat), []]
                blocks.append(current)
                continue
            bm = BONUS_RE.match(ln)
            if bm:
                cat = "Huevos" if "huevo" in bm.group(1).lower() else "Bonuses"
                current = [cat, []]
                blocks.append(current)
                # keep the descriptive bonus title as the first content line
                add(bm.group(1).strip())
                continue
            # split inline "<name> Ingredientes:" into two logical lines
            im = INLINE_ING_RE.match(ln)
            if im and not ln.lower().startswith("ingredientes"):
                add(im.group(1).strip())
                add("Ingredientes:")
                continue
            add(ln)
    return [(c, merge_lone_bullets(lines)) for c, lines in blocks]


def merge_lone_bullets(lines):
    """Join a standalone bullet marker line (e.g. '●') with its following text
    line, so bullets are always '● <texto>'. The PDF often puts the marker on
    its own line, which makes one-word ingredients (e.g. 'Sal') look like titles.
    """
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if re.fullmatch(r"[●○▪•◦]", ln):
            j = i + 1
            while j < len(lines) and lines[j] == "":
                j += 1
            if j < len(lines):
                out.append(ln + " " + lines[j])
                i = j + 1
                continue
        out.append(ln)
        i += 1
    return out


def is_prose(line: str) -> bool:
    return line.endswith(".") or len(line) > 60 or ". " in line


def is_title_line(line: str) -> bool:
    """A standalone, capitalized recipe-title line (or a Variación:/Para hacer name)."""
    if not line:
        return False
    if NAME_PREFIX_RE.match(line):
        return True
    if BULLET_RE.match(line) or STEP_RE.match(line) or not line[0].isalpha() or line[0].islower():
        return False
    if SKIP_TITLE_RE.match(line) or SUBLABEL_RE.match(line):
        return False
    return not is_prose(line)


def title_text(line: str) -> str:
    m = NAME_PREFIX_RE.match(line)
    return (m.group(1) if m else line).strip()


def ends_with_connector(line: str) -> bool:
    last = line.rsplit(" ", 1)[-1].lower().strip(".,")
    return last in CONNECTORS or line.endswith("&")


def backward_name(lines, anchor, lower_bound):
    """Scan upward from the line above `anchor` to find name + servings + notes.

    Handles wrapped names (a lowercase continuation line directly below or a
    connector-ending head line directly above the title) and skips intro prose,
    `Rinde`/`Sirve` (captured as servings), and `Total:`/`Activo:` metadata.
    """
    notes, servings = [], None
    wrap, wrap_broken = [], False  # non-title lines seen before any title
    name = None
    i = anchor - 1
    while i >= lower_bound:
        ln = lines[i]
        if STEP_RE.match(ln) or PROC_RE.match(ln) or ING_RE.match(ln) or BULLET_RE.match(ln):
            break
        if ln == "":
            if name is not None:
                break
            if wrap:
                wrap_broken = True
            i -= 1
            continue
        sm = SERV_RE.match(ln)
        if sm:
            servings = servings or sm.group(1).strip()
            if wrap:
                wrap_broken = True
            i -= 1
            continue
        if is_title_line(ln):
            t = title_text(ln)
            if name is None:
                name = t
                if wrap and (ends_with_connector(t) or not wrap_broken):
                    name = t + " " + " ".join(reversed(wrap))
            else:
                # a higher line: prepend only if it continues the name
                if name[:1].islower() or ends_with_connector(t):
                    name = t + " " + name
                else:
                    break
        else:
            if name is not None:
                notes.append(ln)
                break
            # candidate wrap continuation vs intro prose
            if not is_prose(ln) and len(ln) < 60 and not SKIP_TITLE_RE.match(ln):
                wrap.append(ln)
            else:
                notes.append(ln)
                wrap_broken = True
        i -= 1
    name = re.sub(r"\s+", " ", name).strip() if name else None
    notes.reverse()
    return name, servings, notes


def parse_ingredients(lines):
    items, notes = [], []
    cur = None

    def flush():
        nonlocal cur
        if cur is not None:
            t = re.sub(r"\s+", " ", cur).strip()
            if t:
                items.append(t)
        cur = None

    note_mode = False
    for ln in lines:
        if ln == "":
            continue
        if SERV_RE.match(ln):
            continue
        bm = BULLET_RE.match(ln)
        if bm:
            flush()
            cur = bm.group(1)
            note_mode = False
        elif (ln.lower().startswith("ingredientes") or SUBLABEL_RE.match(ln)
              or ln.startswith("ANTES")):
            flush()
            notes.append(ln)
            note_mode = True
        elif note_mode:
            notes.append(ln)
        elif is_prose(ln) and ln[0].isupper():
            # a trailing intro/instruction paragraph, not an ingredient
            flush()
            notes.append(ln)
            note_mode = True
        else:
            cur = ln if cur is None else cur + " " + ln
    flush()
    return items, notes


def parse_steps(lines):
    steps, notes = [], []
    cur = None

    def flush():
        nonlocal cur
        if cur is not None:
            t = re.sub(r"\s+", " ", cur).strip()
            if t:
                steps.append(t)
        cur = None

    for ln in lines:
        if ln == "":
            continue
        sm = STEP_RE.match(ln)
        if sm:
            flush()
            cur = sm.group(2)
        elif cur is None and SUBLABEL_RE.match(ln):
            notes.append(ln)
        else:
            cur = ln if cur is None else cur + " " + ln
    flush()
    return steps, notes


def segment_block(category, lines):
    markers = []  # (kind, idx)
    for i, l in enumerate(lines):
        if ING_RE.match(l):
            markers.append(("ING", i))
        elif PROC_RE.match(l):
            markers.append(("PROC", i))
    if not markers:
        return []

    recipes = []
    pending_ings = []
    prev_marker_idx = -1

    def next_marker_after(idx):
        for kind, mi in markers:
            if mi > idx:
                return mi
        return len(lines)

    def emit(ing_idxs, proc_idx):
        nonlocal prev_marker_idx
        ingredients, ing_notes, servings = [], [], None

        if ing_idxs:
            anchor = ing_idxs[0]
            for g in ing_idxs:
                grp = lines[g + 1:next_marker_after(g)]
                its, nts = parse_ingredients(grp)
                ingredients += its
                ing_notes += nts
                if servings is None:
                    for l in grp:
                        sm = SERV_RE.match(l)
                        if sm:
                            servings = sm.group(1).strip()
                            break
        else:
            # No "Ingredientes:" header: gather bullet lines directly above the
            # procedure (variant recipes like Aioli, Pasta Alfredo).
            j = proc_idx - 1
            buf = []
            while j > prev_marker_idx:
                ln = lines[j]
                if ING_RE.match(ln) or PROC_RE.match(ln) or is_title_line(ln):
                    break
                if ln == "":
                    if buf:
                        break
                    j -= 1
                    continue
                buf.append(ln)
                j -= 1
            buf.reverse()
            anchor = j + 1
            ingredients, ing_notes = parse_ingredients(buf)

        name, servings2, name_notes = backward_name(lines, anchor, prev_marker_idx + 1)
        servings = servings or servings2

        steps, step_notes = [], []
        if proc_idx is not None:
            steps, step_notes = parse_steps(lines[proc_idx + 1:next_marker_after(proc_idx)])

        if not name:
            m = ING_RE.match(lines[anchor]) if ing_idxs else None
            suf = (m.group(1) or "").strip(" :") if m else ""
            suf = re.sub(r"^(de|del|para)\s+", "", suf, flags=re.IGNORECASE)
            name = suf or None

        if name and len(name) <= 2:  # stray fragment, not a real title
            name = None
        # Bound the next recipe's upward name scan at this recipe's procedure
        # (backward_name additionally stops at any step/proc/ingredient line).
        prev_marker_idx = proc_idx if proc_idx is not None else anchor

        rec = {
            "name": name,
            "category": category,
            "servings": servings,
            "ingredients": ingredients,
            "steps": steps,
            "notes": [n for n in (name_notes + ing_notes + step_notes) if n],
        }
        # Merge fragments that are clearly not standalone recipes into the
        # previous recipe: nameless tiny bits, or serving/variation note blocks.
        is_note_block = (
            (name is None and len(ingredients) <= 1 and len(steps) <= 1)
            or (not ingredients and name and NONRECIPE_NAME_RE.match(name))
        )
        if is_note_block and recipes:
            recipes[-1]["steps"] += steps
            recipes[-1]["notes"] += ([name] if name else []) + rec["notes"]
        elif name or ingredients or steps:
            recipes.append(rec)

    for kind, idx in markers:
        if kind == "ING":
            pending_ings.append(idx)
        else:  # PROC
            emit(pending_ings, idx)
            pending_ings = []
    if pending_ings:  # trailing ingredient group with no procedure
        emit(pending_ings, None)
    return recipes


def parse_all():
    recipes = []
    for cat, lines in load_blocks():
        recipes.extend(segment_block(cat, lines))
    return recipes


if __name__ == "__main__":
    recipes = parse_all()
    print(f"TOTAL recipes: {len(recipes)}\n")
    for i, r in enumerate(recipes):
        nm = (r["name"] or "??")[:46]
        print(f"[{i:02d}] {r['category'][:13]:<13} | {nm:<46} "
              f"| serv={str(r['servings'])[:14]:<14} ing={len(r['ingredients']):<2} steps={len(r['steps'])}")

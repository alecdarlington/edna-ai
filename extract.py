"""Extract recipes from the Recetas PDF into recipes.json.

Pipeline:
  1. parse_core.parse_all()  -> deterministic structure (name, category,
     servings, ingredients, steps) straight from the PDF text.
  2. Claude API (hybrid)      -> ingredients_normalized (core names, lowercase,
     singular, Spanish), active/total time estimates, and a repaired name for the
     handful of variant/sauce recipes whose title the parser couldn't resolve.
     If no ANTHROPIC_API_KEY is available, a rule-based fallback is used so the
     script always runs offline.
  3. tables                   -> reference tables (images) transcribed to a
     separate "tables" section  (see transcribe_tables.py).

Usage:
  python extract.py                 # all recipes -> recipes.json
  python extract.py --limit 5       # first 5 only (review checkpoint)
  python extract.py --no-llm        # force rule-based fallback
"""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import parse_core

MODEL = "claude-sonnet-4-6"
SERV_LEAD_RE = re.compile(r"^(a|de|para)\s+", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# servings cleanup                                                            #
# --------------------------------------------------------------------------- #
def clean_servings(s):
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    s = SERV_LEAD_RE.sub("", s)
    return s or None


# --------------------------------------------------------------------------- #
# API key                                                                     #
# --------------------------------------------------------------------------- #
def load_api_key():
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


# --------------------------------------------------------------------------- #
# Claude-based enrichment                                                      #
# --------------------------------------------------------------------------- #
SYS_PROMPT = (
    "Eres un asistente de cocina que normaliza recetas en español. "
    "Respondes SIEMPRE y SOLO con un objeto JSON válido, sin texto adicional."
)

NORM_RULES = """Reglas para los nombres normalizados (NOMBRE BASE de cada ingrediente):
- en minúscula y en singular.
- SIN cantidades, unidades ni descripciones de preparación, estado o calidad.
  Elimina adjetivos como: molido(a), seco(a), fresco(a), picado(a), rallado(a),
  deshuesado(a), entero(a), grande, mediano(a), chico(a), pequeño(a), recién,
  en polvo, en grano, virgen, extra, finamente, cortado(a), partido(a), etc.
- elimina también el color en vegetales: "cebolla morada" -> "cebolla";
  "pimentón rojo" -> "pimentón".
- CONSERVA solo los calificativos que identifican un ingrediente DISTINTO:
  "aceite de oliva", "salsa de soya", "caldo de pollo"/"caldo de res",
  "pasta de tomate", "tortilla de maíz", "vino tinto"/"vino blanco",
  "vinagre de sidra", "queso parmesano"/"queso feta", "chile chipotle"/
  "chile ancho", y el tipo de cítrico ("limón verde", "limón amarillo").
Ejemplos: "2 cebollas amarillas grandes" -> "cebolla"; "Sal kosher" -> "sal";
"4 cucharadas de aceite de oliva extra virgen" -> "aceite de oliva";
"2 cucharaditas de comino molido" -> "comino"; "2 hojas de laurel" -> "laurel";
"3 libras de costillas de res deshuesadas" -> "costilla de res";
"Sal kosher y pimienta negra recién molida" -> "sal y pimienta negra"."""

USER_TMPL = """Receta (en español):
Nombre detectado: {name}
Categoría: {category}
Ingredientes:
{ingredients}
Procedimiento:
{steps}

""" + NORM_RULES + """

Devuelve un JSON con exactamente estas llaves:
- "ingredients_normalized": el nombre base de CADA línea de ingrediente, en el
  mismo orden. La lista debe tener EXACTAMENTE {n_ing} elementos: UNO por cada
  línea de ingrediente. NO combines líneas distintas: si "Sal" y "Pimienta
  negra" están en líneas separadas, devuelve dos elementos ("sal", "pimienta
  negra"). Solo cuando UNA misma línea ya contiene varios ("Sal y pimienta"),
  devuélvela como un solo elemento ("sal y pimienta"). Nunca dividas una línea
  en dos.
- "active_time_minutes": entero, minutos de TRABAJO ACTIVO (lo que requiere
  atención: picar, sofreír, revolver, licuar, armar). NO incluyas esperas
  pasivas (hervor/cocción a fuego lento sin atención, horneado o braseado
  prolongado, marinado, salmuera, reposo, enfriado).
- "total_time_minutes": entero, tiempo total de principio a fin (activo +
  pasivo), incluyendo esperas como marinado, braseado, reposo y enfriado.
  Debe ser >= active_time_minutes. Si el procedimiento indica tiempos, úsalos.
- "difficulty": nivel de dificultad, exactamente uno de "fácil", "intermedio"
  o "difícil", según el número de pasos, las técnicas requeridas (p. ej.
  emulsionar, dorar en tandas, templar, mantequilla avellanada, cortes) y la
  precisión necesaria; no por el tiempo de espera pasiva.
- "name_clean": el nombre correcto y limpio de la receta en español. Si el
  nombre detectado ya es correcto, repítelo; si parece basura (un fragmento,
  un tiempo, vacío), dedúcelo del contenido.

Responde solo con el JSON."""

# For variant recipes that have NO ingredient list (ingredients are mentioned
# inside the steps), extract the list from the procedure too.
USER_TMPL_EMBED = """Receta (en español) SIN lista de ingredientes; los
ingredientes están mencionados dentro del procedimiento.
Nombre detectado: {name}
Categoría: {category}
Procedimiento:
{steps}

""" + NORM_RULES + """

Devuelve un JSON con exactamente estas llaves:
- "ingredients": lista de los ingredientes mencionados en el procedimiento, tal
  como aparecen (incluye la cantidad si se indica). Excluye utensilios y el
  agua de cocción genérica.
- "ingredients_normalized": el nombre base de cada ingrediente, MISMO orden y
  MISMO número de elementos que "ingredients".
- "active_time_minutes": entero, minutos de trabajo activo (sin esperas pasivas).
- "total_time_minutes": entero, tiempo total de principio a fin (activo +
  pasivo). Debe ser >= active_time_minutes.
- "difficulty": exactamente uno de "fácil", "intermedio" o "difícil", según los
  pasos, las técnicas requeridas y la precisión necesaria.
- "name_clean": el nombre correcto y limpio de la receta en español.

Responde solo con el JSON."""


def build_client(key):
    from anthropic import Anthropic
    return Anthropic(api_key=key)


def enrich_llm(client, rec):
    steps_txt = "\n".join(f"{n}. {s}" for n, s in enumerate(rec["steps"], 1)) or "(ninguno)"
    embed = not rec["ingredients"] and bool(rec["steps"])
    if embed:
        prompt = USER_TMPL_EMBED.format(
            name=rec["name"] or "(desconocido)", category=rec["category"], steps=steps_txt)
        expect = None  # length defined by the model's own "ingredients" list
    else:
        prompt = USER_TMPL.format(
            name=rec["name"] or "(desconocido)", category=rec["category"],
            n_ing=len(rec["ingredients"]),
            ingredients="\n".join(f"- {i}" for i in rec["ingredients"]) or "(ninguno)",
            steps=steps_txt)
        expect = len(rec["ingredients"])

    last_err = None
    for _ in range(2):
        msg = client.messages.create(
            model=MODEL, max_tokens=1024, system=SYS_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        data = json.loads(text)
        norm = data.get("ingredients_normalized", [])
        target = len(data.get("ingredients", [])) if embed else expect
        if len(norm) == target:
            return data
        last_err = f"normalized={len(norm)} vs expected={target}"
        prompt += ("\n\nCORRECCIÓN: 'ingredients_normalized' debe tener el MISMO "
                   "número de elementos que la lista de ingredientes, uno por uno.")
    raise ValueError(last_err)


# --------------------------------------------------------------------------- #
# Rule-based fallback (offline)                                               #
# --------------------------------------------------------------------------- #
UNITS = (
    "tazas?|cucharad(?:as?|itas?)|libras?|lbs?|kilos?|kg|gramos?|gr?|onzas?|oz|"
    "ml|mililitros?|litros?|l|qts?|cuartos?|dientes?|ramos?|ramit[ao]s?|tallos?|"
    "hojas?|latas?|pizcas?|gajos?|trozos?|rodajas?|rebanadas?|pu[ñn]ados?|"
    "filetes?|pechugas?|manojos?|pulgadas?|generos[oa]s?"
)
QTY_RE = re.compile(
    r"^\s*(?:\d+[\d/.,’'\s½¼¾⅓⅔⅛-]*|[½¼¾⅓⅔⅛]+|al gusto)?\s*"
    r"(?:\((?:[^)]*)\)\s*)?(?:de\s+)?(?:(?:%s)\b\s*)*(?:de\s+)?" % UNITS,
    re.IGNORECASE,
)
ADJ = {
    "grande", "grandes", "mediano", "mediana", "medianos", "medianas", "chico",
    "chica", "chicos", "chicas", "pequeño", "pequeña", "pequeños", "pequeñas",
    "fresco", "fresca", "frescos", "frescas", "seco", "seca", "secos", "secas",
    "molido", "molida", "picado", "picada", "fino", "fina", "finos", "finas",
    "amarillo", "amarilla", "rojo", "roja", "verde", "morado", "morada",
    "entero", "entera", "extra", "virgen", "kosher", "negro", "negra",
}
SING = [("ces", "z"), ("es", ""), ("s", "")]


def singularize(w):
    for suf, rep in SING:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)] + rep
    return w


def normalize_rule(text):
    t = text.lower().strip()
    t = re.sub(r"\([^)]*\)", "", t)            # drop parentheticals
    t = re.split(r"[,;]| o | para | sin ", t)[0]  # drop trailing descriptors
    t = QTY_RE.sub("", t).strip()
    t = re.sub(r"\s+", " ", t).strip(" .-")
    words = [w for w in t.split() if w not in ADJ]
    # keep a compact head: noun (+ "de X" qualifier, e.g. "aceite de oliva")
    if "de" in words:
        i = words.index("de")
        head = words[: i + 2]
    else:
        head = words[:1]
    head = [singularize(w) if w not in {"de", "oliva", "ajo", "sal"} else w for w in head]
    return " ".join(head).strip() or text.lower()


def estimate_times_rule(steps):
    """Rough (active, total) minutes from explicit durations in the steps.

    Durations under ~30 min are treated as active work; longer ones (simmering,
    braising, marinating, resting) are counted only toward the total.
    """
    joined = " ".join(steps).lower()
    active = passive = 0
    for m in re.finditer(r"(\d+)\s*(?:a|-|–|y)?\s*(\d+)?\s*(min|minuto|hora|hr)", joined):
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        val = (lo + hi) / 2
        if m.group(3).startswith("h"):
            val *= 60
        if val <= 30:
            active += val
        else:
            passive += val
    if active or passive:
        active = int(round(active)) or min(30, max(10, 8 * len(steps)))
        return active, int(round(active + passive))
    base = max(10, 8 * len(steps))
    return base, base


TECHNIQUE_RE = re.compile(
    r"emulsion|dorar|temple|templ|avellan|brasea|escalf|salmuera|reduc|"
    r"licu[ae]|confit|gratin|marin", re.IGNORECASE)


def difficulty_rule(rec, active):
    """Heuristic difficulty from step count, active time, and techniques."""
    n = len(rec["steps"])
    techy = bool(TECHNIQUE_RE.search(" ".join(rec["steps"])))
    if n <= 3 and active <= 20 and not techy:
        return "fácil"
    if n >= 8 or active >= 60 or (techy and n >= 6):
        return "difícil"
    return "intermedio"


def enrich_rule(rec):
    active, total = estimate_times_rule(rec["steps"])
    return {
        "ingredients_normalized": [normalize_rule(i) for i in rec["ingredients"]],
        "active_time_minutes": active,
        "total_time_minutes": total,
        "difficulty": difficulty_rule(rec, active),
        "name_clean": rec["name"],
    }


# --------------------------------------------------------------------------- #
# name-repair gate                                                            #
# --------------------------------------------------------------------------- #
def name_is_bad(name):
    if not name:
        return True
    if len(name) < 5 or name[0].islower():
        return True
    return bool(re.search(r"minutos|:|\?\?|^líquidos", name))


# --------------------------------------------------------------------------- #
# main                                                                        #
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--out", default="recipes.json")
    args = ap.parse_args()

    recipes = parse_core.parse_all()
    if args.limit:
        recipes = recipes[: args.limit]
    for r in recipes:
        r["servings"] = clean_servings(r["servings"])

    key = "" if args.no_llm else load_api_key()
    use_llm = bool(key)
    if not use_llm:
        print("WARNING: no ANTHROPIC_API_KEY -> using offline rule-based fallback.",
              file=sys.stderr)

    client = build_client(key) if use_llm else None

    def process(rec):
        try:
            enr = enrich_llm(client, rec) if use_llm else enrich_rule(rec)
        except Exception as e:  # noqa: BLE001 - fall back per-recipe on API error
            print(f"  ! {rec['name']}: {e}; using rule fallback", file=sys.stderr)
            enr = enrich_rule(rec)
        name = rec["name"]
        if name_is_bad(name):
            name = enr.get("name_clean") or name
        # embed path: ingredients were extracted from the steps by the model
        ingredients = rec["ingredients"] or enr.get("ingredients", [])
        return {
            "name": name,
            "category": rec["category"],
            "servings": rec["servings"],
            "ingredients": ingredients,
            "ingredients_normalized": enr.get("ingredients_normalized", []),
            "steps": rec["steps"],
            "active_time_minutes": enr.get("active_time_minutes"),
            "total_time_minutes": enr.get("total_time_minutes"),
            "difficulty": enr.get("difficulty"),
            "notes": rec.get("notes", []),
        }

    if use_llm:
        with ThreadPoolExecutor(max_workers=6) as ex:
            out = list(ex.map(process, recipes))
    else:
        out = [process(r) for r in recipes]

    payload = {"recipes": out}
    # preserve a previously-merged "tables" section if re-running
    if os.path.exists(args.out):
        try:
            prev = json.load(open(args.out, encoding="utf-8"))
            if prev.get("tables"):
                payload["tables"] = prev["tables"]
        except (OSError, ValueError):
            pass
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(out)} recipes -> {args.out}"
          + (" (tables preserved)" if "tables" in payload else ""))


if __name__ == "__main__":
    main()

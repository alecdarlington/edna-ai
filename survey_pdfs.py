"""
survey_pdfs.py — cheap triage of new Edna PDFs before any extraction work

Uses pdftotext only (no LLM calls, no vision). For each PDF it reports:
  - page count (from pdftotext's form-feed page separators)
  - text-layer quality: characters per page, and how many pages are near-empty
  - a content profile from Spanish keyword counts (recipes / teaching / tips / planning)

Usage:
  python survey_pdfs.py            # survey every PDF in the folder
  python survey_pdfs.py file.pdf   # survey one
"""

import glob
import os
import subprocess
import sys
import tempfile
import unicodedata

# Pages with fewer characters than this are treated as having no usable text —
# typical of a full-page image or a photo-only spread.
EMPTY_PAGE_CHARS = 80

# Below this average, the document as a whole needs OCR/vision rather than parsing.
IMAGE_BASED_CPP = 150

# Keyword families. Counted on accent-stripped lowercase text so "ácido"/"acido"
# and "Preparación"/"preparacion" both hit.
SIGNALS = {
    "recipes": [
        "ingredientes", "procedimiento", "preparacion", "porciones", "rinde",
        "cucharada", "cucharadita", "taza", "gramos", "al gusto",
    ],
    "teaching": [
        "tecnica", "por que", "sal ", "grasa", "acido", "calor", "temperatura",
        "sabor", "textura", "aprende", "pilar",
    ],
    "tips": [
        "hack", "tip", "consejo", "truco", "error", "evita", "recuerda",
    ],
    "planning": [
        "planificacion", "meal plan", "menu", "semana", "lista de compras",
        "sistema 3x5", "organiza", "batch",
    ],
}


def norm(text: str) -> str:
    """Lowercase and strip accents so keyword matching is robust."""
    lowered = text.lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", lowered)
        if unicodedata.category(c) != "Mn"
    )


def extract(path: str) -> str | None:
    """Run pdftotext and return the whole document text, or None on failure.

    The file is copied to a temporary ASCII path first. Some of these PDFs came
    from a Mac and carry decomposed accents (i + U+0301) in the filename, which
    this pdftotext build (Xpdf 4.00) mangles to latin-1 and cannot open; it also
    has no stdin mode, so a temp copy is the only way through.
    """
    try:
        data = open(path, "rb").read()
    except OSError:
        return None

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(data)
            tmp = fh.name
        out = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", tmp, "-"],
            capture_output=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", errors="replace")


def survey(path: str) -> dict:
    raw = extract(path)
    if raw is None:
        return {"path": path, "error": "pdftotext failed"}

    # pdftotext emits \f between pages, so the split gives per-page text.
    pages = raw.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]          # trailing separator, not a real page

    n = len(pages) or 1
    chars = [len(p.strip()) for p in pages]
    total = sum(chars)
    cpp = total / n
    empty = sum(1 for c in chars if c < EMPTY_PAGE_CHARS)

    flat = norm(raw)
    counts = {
        family: sum(flat.count(word) for word in words)
        for family, words in SIGNALS.items()
    }

    # Structural markers give a firmer recipe count than keywords alone. The
    # workbooks head their steps "Procedimiento:", but the newer PDFs use
    # "Preparación:" / "Pasos:", so count all three or the newer files read as
    # having zero recipes despite carrying dozens of ingredient lists.
    step_markers = {
        "procedimiento": flat.count("procedimiento"),
        "preparacion": flat.count("preparacion"),
        "pasos": flat.count("pasos"),
    }
    recipe_blocks = max(step_markers.values())
    ingredient_blocks = flat.count("ingredientes")

    # Garbled text layers show up as replacement characters.
    bad = raw.count("�")

    return {
        "path": path,
        "pages": n,
        "chars": total,
        "cpp": cpp,
        "empty_pages": empty,
        "counts": counts,
        "recipe_blocks": recipe_blocks,
        "step_markers": step_markers,
        "ingredient_blocks": ingredient_blocks,
        "garbled": bad,
        "sample": next((p.strip() for p in pages if len(p.strip()) > 200), ""),
    }


def verdict(r: dict) -> str:
    """Classify the text layer."""
    if r["cpp"] < IMAGE_BASED_CPP:
        return "IMAGE-BASED — needs OCR/vision"
    share = r["empty_pages"] / r["pages"]
    if share > 0.4:
        return f"MIXED — {r['empty_pages']}/{r['pages']} pages have no text"
    if r["garbled"] > 20:
        return f"CLEAN but {r['garbled']} bad chars — check encoding"
    return "CLEAN text layer"


def profile(r: dict) -> str:
    """Describe the dominant content type by keyword share."""
    c = r["counts"]
    total = sum(c.values()) or 1
    ranked = sorted(c.items(), key=lambda kv: -kv[1])
    parts = [f"{k} {round(100 * v / total)}%" for k, v in ranked if v]
    return ", ".join(parts) if parts else "no signals"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    targets = sys.argv[1:] or sorted(glob.glob("*.pdf"))
    if not targets:
        print("No PDFs found.")
        sys.exit(1)

    results = []
    for path in targets:
        r = survey(path)
        results.append(r)
        name = path[:62]
        if "error" in r:
            print(f"\n{'='*78}\n{name}\n  ERROR: {r['error']}")
            continue

        print(f"\n{'='*78}")
        print(f"{name}")
        print(f"  pages={r['pages']:<4} chars={r['chars']:<7} chars/page={r['cpp']:.0f}"
              f"  empty_pages={r['empty_pages']}")
        print(f"  text layer : {verdict(r)}")
        print(f"  content    : {profile(r)}")
        marks = ", ".join(f"{k} x{v}" for k, v in r["step_markers"].items() if v)
        print(f"  structure  : 'Ingredientes' x{r['ingredient_blocks']}"
              f"   steps: {marks or 'none found'}")
        snippet = " ".join(r["sample"].split())[:260]
        print(f"  first text : {snippet}")

    print(f"\n{'='*78}\nSUMMARY ({len(results)} files)")
    for r in results:
        if "error" in r:
            print(f"  !! {r['path'][:52]:<54} ERROR")
            continue
        tag = "IMG " if r["cpp"] < IMAGE_BASED_CPP else "TEXT"
        print(f"  {tag} {r['path'][:52]:<54} {r['pages']:>4}p  "
              f"{r['cpp']:>5.0f} c/p  recipes~{r['recipe_blocks']}")

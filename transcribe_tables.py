"""Transcribe the reference tables (which are embedded images, not text) into a
structured "tables" section and merge it into recipes.json.

Each table is rendered to PNG with PyMuPDF and transcribed by Claude vision into
JSON {title, description, columns, rows, source}. Requires ANTHROPIC_API_KEY.

Usage:
  python transcribe_tables.py                  # -> tables.json
  python transcribe_tables.py --merge recipes.json
"""
import argparse
import base64
import json
import re

import fitz

from extract import load_api_key, build_client

PDF_PATH = "Workbook Conquista La Cocina - Edna Cochez - Recetas (1).pdf"
MODEL = "claude-sonnet-4-6"

# title, key, and 0-based PDF page indices that make up each table
TABLES = [
    ("Ácidos del Mundo", "acidos_del_mundo", [128, 129, 130, 131]),
    ("Cuándo agregar la sal a tus proteínas (Calendario de Salar)",
     "calendario_de_salar", [132]),
    ("Cuánta sal agregar por peso (Guía de Salar)", "sal_por_peso", [133]),
    ("Grasas del Mundo", "grasas_del_mundo", [134]),
    ("Tabla de temperaturas de cocción de carnes",
     "temperaturas_coccion", [135]),
    ("Tipos de cocción para distintos tipos de carne",
     "tipos_de_coccion", [136]),
    ("Vegetales y Cocciones recomendadas", "vegetales_cocciones", [137]),
    ("4 ensaladas clásicas", "cuatro_ensaladas_clasicas", [138]),
]

PROMPT = """Estas imágenes son una tabla de un recetario en español titulada:
"{title}".

Transcribe la tabla COMPLETA a un objeto JSON con esta forma exacta:
{{
  "title": "{title}",
  "description": "breve descripción de qué muestra la tabla",
  "columns": ["...", "..."],
  "rows": [
    {{"label": "encabezado de fila", "values": {{"<columna>": "<contenido>"}}}}
  ],
  "source": "nota de fuente al pie, si aparece"
}}

Reglas:
- Mantén TODO el texto en español, tal como aparece.
- Si una tabla abarca varias imágenes (continentes/secciones), únelas en una
  sola lista de columnas/filas.
- Para tablas tipo matriz con celdas marcadas por color, pon en cada celda
  'sí' si la celda está coloreada/marcada y '' si está vacía; conserva
  cualquier texto que aparezca dentro de la celda (p. ej. 'Pre-hervidos').
- NO uses comillas dobles (") dentro de los valores de texto; si necesitas
  comillas usa comillas simples (') para que el JSON sea válido.
- Responde SOLO con el JSON válido, sin texto adicional."""


def page_png_b64(doc, idx, zoom=2.4):
    pix = doc[idx].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    return base64.standard_b64encode(pix.tobytes("png")).decode()


def transcribe(client, doc, title, idxs):
    content = [{"type": "text", "text": PROMPT.format(title=title)}]
    for idx in idxs:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png",
                       "data": page_png_b64(doc, idx)},
        })
    msgs = [{"role": "user", "content": content}]
    last_err = None
    for _ in range(2):
        msg = client.messages.create(model=MODEL, max_tokens=8192, messages=msgs)
        text = msg.content[0].text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_err = e
            msgs += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": (
                    f"Ese JSON es inválido ({e}). Probablemente hay comillas "
                    "dobles sin escapar dentro de un valor. Devuelve OTRA VEZ el "
                    "JSON completo y válido, usando comillas simples dentro de los "
                    "valores. Responde solo con el JSON.")},
            ]
    raise last_err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", help="recipes.json to add a 'tables' key to")
    ap.add_argument("--out", default="tables.json")
    args = ap.parse_args()

    key = load_api_key()
    if not key:
        raise SystemExit("No ANTHROPIC_API_KEY found (env or .env).")
    client = build_client(key)
    doc = fitz.open(PDF_PATH)

    tables = []
    for title, tkey, idxs in TABLES:
        print(f"transcribing: {title} ...")
        data = transcribe(client, doc, title, idxs)
        data["key"] = tkey
        data["pdf_pages"] = [i + 1 for i in idxs]
        tables.append(data)

    if args.merge:
        with open(args.merge, encoding="utf-8") as f:
            doc_json = json.load(f)
        doc_json["tables"] = tables
        with open(args.merge, "w", encoding="utf-8") as f:
            json.dump(doc_json, f, ensure_ascii=False, indent=2)
        print(f"Merged {len(tables)} tables into {args.merge}")
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"tables": tables}, f, ensure_ascii=False, indent=2)
        print(f"Wrote {len(tables)} tables -> {args.out}")


if __name__ == "__main__":
    main()

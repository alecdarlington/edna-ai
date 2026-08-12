"""Enrich the Teoría chunks into theory.json (pillar + clean topic; split big
sections into concepts with VERBATIM content).

Deterministic chunking (theory_parse.py) gives faithful concept chunks split on
headings. This pass uses the Claude API to:
  - assign the pillar (sal/grasa/acido/calor/general) from the content,
  - produce a short, search-friendly topic title,
  - split oversized chunks (> SPLIT_CHARS) into sub-concepts, copying the text
    verbatim (validated by coverage — falls back to the whole chunk if the model
    altered or dropped text).

Usage: python theory.py            (-> theory.json)
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

import theory_parse
from extract import load_api_key, build_client

MODEL = "claude-sonnet-4-6"
SPLIT_CHARS = 2200
PILLARS = {"sal", "grasa", "acido", "calor", "general"}

SYS = ("Organizas material didáctico de cocina en español para búsqueda. "
       "Respondes SIEMPRE y SOLO con JSON válido.")

META_TMPL = """Fragmento de un curso de cocina (pilar sugerido: {hint}).
Título actual: {topic}
Contenido:
\"\"\"
{content}
\"\"\"

Devuelve JSON:
- "pillar": uno de "sal", "grasa", "acido", "calor", "general" (según el TEMA del
  contenido, no según el título).
- "topic": un título corto y claro en español (máx ~8 palabras) que describa el
  concepto, útil para búsqueda.
Responde solo con el JSON."""

SPLIT_TMPL = """Fragmento LARGO de un curso de cocina (pilar sugerido: {hint}).
Título actual: {topic}
Contenido:
\"\"\"
{content}
\"\"\"

Divídelo en varios sub-conceptos consecutivos para búsqueda. Devuelve JSON:
- "pillar": uno de "sal","grasa","acido","calor","general".
- "segments": lista de objetos {{"topic": "...", "content": "..."}} donde:
  * "content" es texto COPIADO LITERALMENTE del contenido de arriba, en orden,
    SIN parafrasear, SIN resumir y SIN omitir nada. Concatenados, los segmentos
    deben reproducir TODO el contenido original.
  * cada "topic" es un título corto en español (máx ~8 palabras).
  * usa entre 2 y 6 segmentos, cada uno de un solo concepto.
Responde solo con el JSON."""


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def _alnum(s):
    """Alphanumeric-only lowercase stream (ignores punctuation/quote/space diffs)."""
    return re.sub(r"[^0-9a-záéíóúñü]", "", s.lower())


def call_json(client, prompt, tokens=4096):
    msgs = [{"role": "user", "content": prompt}]
    last = None
    for _ in range(2):
        msg = client.messages.create(model=MODEL, max_tokens=tokens, system=SYS,
                                     messages=msgs)
        text = msg.content[0].text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last = e
            msgs += [{"role": "assistant", "content": text},
                     {"role": "user", "content":
                      f"Ese JSON es inválido ({e}). Devuélvelo completo y válido, "
                      "escapando correctamente las comillas dobles dentro de los "
                      "textos. Responde solo con el JSON."}]
    raise last


def fix_pillar(p, fallback):
    p = (p or "").strip().lower()
    p = {"ácido": "acido", "ácidos": "acido", "acidos": "acido",
         "grasas": "grasa", "calor ": "calor"}.get(p, p)
    return p if p in PILLARS else fallback


def enrich_chunk(client, ch):
    hint = ch["pillar"]
    if len(ch["content"]) > SPLIT_CHARS:
        try:
            data = call_json(client, SPLIT_TMPL.format(
                hint=hint, topic=ch["topic"], content=ch["content"]), tokens=8192)
            segs = data.get("segments", [])
            joined = _alnum(" ".join(s.get("content", "") for s in segs))
            orig = _alnum(ch["content"])
            # fidelity: alphanumeric streams must match closely (tolerates only
            # punctuation/whitespace diffs, not paraphrasing or omission)
            ratio = SequenceMatcher(None, orig, joined).ratio()
            if segs and ratio >= 0.97:
                pillar = fix_pillar(data.get("pillar"), hint)
                return [{"pillar": pillar, "topic": s["topic"].strip(),
                         "content": s["content"].strip(), "page": ch["page"]}
                        for s in segs if s.get("content", "").strip()]
            print(f"  ~ split rejected for '{ch['topic'][:40]}' "
                  f"(similarity={ratio:.3f}); keeping whole", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  ! split error '{ch['topic'][:40]}': {e}", file=sys.stderr)

    # metadata only (whole chunk, content untouched)
    try:
        data = call_json(client, META_TMPL.format(
            hint=hint, topic=ch["topic"], content=ch["content"][:4000]), tokens=300)
        return [{"pillar": fix_pillar(data.get("pillar"), hint),
                 "topic": (data.get("topic") or ch["topic"]).strip(),
                 "content": ch["content"], "page": ch["page"]}]
    except Exception as e:  # noqa: BLE001
        print(f"  ! meta error '{ch['topic'][:40]}': {e}", file=sys.stderr)
        return [{"pillar": hint, "topic": ch["topic"], "content": ch["content"],
                 "page": ch["page"]}]


def main():
    key = load_api_key()
    if not key:
        raise SystemExit("No ANTHROPIC_API_KEY found (env or .env).")
    client = build_client(key)
    chunks = theory_parse.build_chunks()
    print(f"{len(chunks)} raw chunks -> enriching ...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda c: enrich_chunk(client, c), chunks))
    out = [c for group in results for c in group]

    with open("theory.json", "w", encoding="utf-8") as f:
        json.dump({"chunks": out}, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(out)} chunks -> theory.json")


if __name__ == "__main__":
    main()

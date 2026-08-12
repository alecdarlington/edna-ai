"""Add the 12 Hacks ebook to theory.json as pillar "general".

Only the hack pages are taken. Page 1 is the cover, page 2 an intro blurb,
page 16 a store promo and page 17 blank — none carry a hack.

Transcription source: the PDF's own text layer, not vision. The survey flagged
this file as image-heavy on bytes-per-page (795 KB/page), but every hack page
turns out to carry its full text (300–1037 chars of complete sentences), so
reading it directly is lossless where a vision pass could introduce errors. Use
--verify to have Claude look at the rendered page and report anything the text
layer is missing.

Any FREEBIE / discount-code line is dropped: those do not belong in the data.

Usage:
  python hacks_to_theory.py                 # dry run, prints the chunks
  python hacks_to_theory.py --verify        # + vision check for missing text
  python hacks_to_theory.py --apply
"""

import json
import re
import shutil
import sys

import fitz

PDF = "Ebook 12 Hacks 2026.pdf"
HACK_PAGES = range(3, 16)          # 3–15 inclusive
PILLAR = "general"

# Promo / coupon lines that must not enter the data.
PROMO_RE = re.compile(
    r"freebie|c[oó]digo|cup[oó]n|descuento|visita la tienda|"
    r"aprovecha mis ebooks|ednacochez\.com|@ednacochez|s[ií]gueme",
    re.IGNORECASE,
)


def page_lines(page) -> list[tuple[str, float]]:
    """Lines with their font size, so a wrapped title can be reassembled."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            t = "".join(s["text"] for s in line["spans"])
            t = t.replace("​", "").replace("\xa0", " ").strip()
            if t:
                size = max((s["size"] for s in line["spans"] if s["text"].strip()),
                           default=0)
                out.append((t, size))
    return out


def split_title(lines: list[tuple[str, float]]) -> tuple[str, str]:
    """Separate the hack's title from its body.

    The title is set in the page's largest font and often wraps: "Pela el
    jengibre" / "con cuchara". Taking only the first line leaves "con cuchara"
    stranded at the front of the body, so every line at title size is claimed.
    """
    if not lines:
        return "", ""
    biggest = max(s for _, s in lines)
    n = 0
    while n < len(lines) and lines[n][1] >= biggest * 0.9:
        n += 1
    topic = re.sub(r"\s+", " ", " ".join(t for t, _ in lines[:n])).strip()
    body = re.sub(r"\s+", " ", " ".join(t for t, _ in lines[n:])).strip()
    return topic, body


def build() -> list[dict]:
    doc = fitz.open(PDF)
    chunks = []
    for pno in HACK_PAGES:
        page = doc[pno - 1]
        lines = [(t, s) for t, s in page_lines(page) if not PROMO_RE.search(t)]
        # Drop a bare page number and the running "12 hacks" mark.
        lines = [(t, s) for t, s in lines
                 if not re.fullmatch(r"\d{1,2}", t)
                 and not re.fullmatch(r"(?i)12\s*hacks?", t)]
        if not lines:
            continue
        topic, body = split_title(lines)
        if not body:
            continue
        chunks.append({
            "pillar": PILLAR,
            "topic": topic,
            "content": body,
            "page": pno,
            "source_pdf": PDF,
        })
    return chunks


def verify(chunks: list[dict]) -> None:
    """Ask Claude to compare the rendered page against what we extracted."""
    import base64

    from extract import build_client, load_api_key

    key = load_api_key()
    if not key:
        print("  (no ANTHROPIC_API_KEY — skipping vision verification)")
        return
    client = build_client(key)
    doc = fitz.open(PDF)

    for ch in chunks:
        page = doc[ch["page"] - 1]
        png = page.get_pixmap(dpi=110).tobytes("png")
        prompt = (
            "Esta es una página de un ebook de trucos de cocina. Del texto de la "
            "página, ya extraje lo siguiente:\n\n"
            f"TÍTULO: {ch['topic']}\nCUERPO: {ch['content']}\n\n"
            "¿Falta algún texto visible en la imagen que NO esté arriba (por "
            "ejemplo texto dentro de una imagen o un gráfico)? Responde solo con "
            "JSON: {\"missing\": true/false, \"texto_faltante\": \"...\"}"
        )
        msg = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=400,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/png",
                                             "data": base64.b64encode(png).decode()}},
                {"type": "text", "text": prompt},
            ]}],
        )
        raw = re.sub(r"^```(?:json)?|```$", "", msg.content[0].text.strip(),
                     flags=re.MULTILINE).strip()
        try:
            data = json.loads(raw)
        except Exception:
            print(f"  p{ch['page']:<3} (unparsed vision reply)")
            continue
        flag = "MISSING" if data.get("missing") else "complete"
        extra = str(data.get("texto_faltante") or "")[:88]
        print(f"  p{ch['page']:<3} {flag:<9} {ch['topic'][:34]:<36} {extra}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    chunks = build()

    print(f"  hack pages taken: {len(chunks)} (of {len(HACK_PAGES)} candidates)")
    for c in chunks:
        print(f"\n  p{c['page']:<3} [{c['pillar']}] {c['topic']}")
        print(f"        {c['content'][:150]}…")

    if "--verify" in sys.argv:
        print("\n  === vision verification ===")
        verify(chunks)

    if "--apply" in sys.argv:
        with open("theory.json", encoding="utf-8") as fh:
            doc = json.load(fh)
        existing = doc if isinstance(doc, list) else doc.get("chunks", [])
        known = {(c.get("topic") or "").lower() for c in existing}
        fresh = [c for c in chunks if c["topic"].lower() not in known]
        print(f"\n  theory.json before: {len(existing)}   adding: {len(fresh)}"
              f"   (skipped {len(chunks) - len(fresh)} already present)")

        shutil.copy("theory.json", "theory.json.bak")
        merged = existing + fresh
        out = merged if isinstance(doc, list) else {**doc, "chunks": merged}
        with open("theory.json", "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        print(f"  theory.json after : {len(merged)}   backup: theory.json.bak")
    else:
        print("\n  dry run — re-run with --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())

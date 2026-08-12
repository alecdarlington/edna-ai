"""Deterministic chunking of the Teoría PDF into concept chunks (no API).

The book is prose under 4 pillars (sal/grasa/ácidos/calor). Headings render at
14-15pt (sub-section) and 24-30pt (pillar/major title); body is 13pt. We split
on headings and keep the teaching text verbatim. A later API pass (theory.py)
assigns the pillar and cleans the topic title.
"""
import re
import fitz

PDF_PATH = "Workbook Conquista La Cocina - Edna Cochez - Teoria  (1).pdf"
ZWSP = "​"
FOOTER_RE = re.compile(r"Edna Cochez.*ednacochez\.com")
RUNHEAD_RE = re.compile(r"^Conquista la Cocina\b")
TERMINAL = ("?", "!", ".", ":")

PILLAR_KEYS = [
    ("sal", re.compile(r"\bLa Sal\b", re.IGNORECASE)),
    ("grasa", re.compile(r"\bgrasas?\b", re.IGNORECASE)),
    ("acido", re.compile(r"\bácidos?\b", re.IGNORECASE)),
    ("calor", re.compile(r"\bCalor\b", re.IGNORECASE)),
]


def clean(t):
    return t.replace(ZWSP, "").replace("\xa0", " ").strip()


def line_items(pg):
    """Return [(size, text)] for each visual line on the page."""
    items = []
    for b in pg.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            txt = clean("".join(s["text"] for s in l["spans"]))
            if not txt:
                continue
            size = max((s["size"] for s in l["spans"]), default=0)
            items.append((round(size, 1), txt))
    return items


def is_chrome(text):
    return (FOOTER_RE.search(text) or RUNHEAD_RE.match(text)
            or text.replace(".", "").isdigit())


def is_heading_size(size):
    return size >= 14


def pillar_of(title, current):
    for name, rx in PILLAR_KEYS:
        if rx.search(title):
            return name
    return current  # inherit (e.g. "Ensaladas", "Punto de Humo", "Mitos...")


def build_chunks():
    doc = fitz.open(PDF_PATH)
    chunks = []
    pillar = "general"
    cur = None  # current chunk dict

    def new_chunk(topic):
        nonlocal cur
        if cur:
            chunks.append(cur)
        cur = {"pillar": pillar, "topic": topic, "_body": [], "page": None}

    pending_head = []  # consecutive heading lines to merge into one title

    def flush_head(page):
        nonlocal pending_head
        if not pending_head:
            return
        title = re.sub(r"\s+", " ", " ".join(pending_head)).strip()
        pending_head = []
        # A very long "heading" is misdetected body -> treat as body text.
        if len(title) > 90:
            if cur:
                cur["_body"].append(title)
            return
        new_chunk(title)
        if cur["page"] is None:
            cur["page"] = page

    def add_body(text, pno):
        nonlocal cur
        flush_head(pno)
        if cur is None:
            new_chunk("Introducción")
            cur["page"] = pno
        cur["_body"].append(text)

    for pno in range(1, len(doc)):  # skip cover page 0
        for size, text in line_items(doc[pno]):
            if is_chrome(text):
                continue
            if is_heading_size(size):
                # prose rendered at heading size (e.g. p85): starts lowercase, or
                # is a long sentence -> treat as body, not a new heading.
                if not pending_head and (text[0].islower()
                                         or (text.endswith(".") and len(text) > 55)):
                    add_body(text, pno)
                    continue
                # merge wrapped heading lines unless the previous ended a phrase
                if pending_head and pending_head[-1].rstrip().endswith(TERMINAL):
                    flush_head(pno)
                if size >= 24:                  # pillar / major title sets the pillar
                    pillar = pillar_of(text, pillar)
                pending_head.append(text)
            else:
                add_body(text, pno)
    flush_head(len(doc))
    if cur:
        chunks.append(cur)

    # finalize: join body; fold empty (heading-only) chunks into the next one
    out = []
    carry = []
    for c in chunks:
        content = re.sub(r"\s{2,}", " ", " ".join(c["_body"])).strip()
        if not content:
            if len(c["topic"]) >= 4:
                carry.append(c["topic"])
            continue
        if carry:
            content = " ".join(carry) + " " + content
            carry = []
        # fold an embedded recipe's "Procedimiento:" into the preceding chunk
        if out and re.match(r"Procedimiento", c["topic"], re.IGNORECASE):
            out[-1]["content"] += "\n" + content
            continue
        out.append({"pillar": c["pillar"], "topic": c["topic"],
                    "content": content, "page": c["page"]})
    return out


if __name__ == "__main__":
    cs = build_chunks()
    print(f"TOTAL chunks: {len(cs)}\n")
    for i, c in enumerate(cs):
        print(f"[{i:02d}] p{c['page']:<3} {c['pillar']:<7} | {c['topic'][:52]:<52} | {len(c['content'])} chars")

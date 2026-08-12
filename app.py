"""
app.py — Conquista la Cocina, Asistente de Edna (Streamlit chat UI)

Run:
  streamlit run app.py
"""

import hashlib
import os

import streamlit as st

from answer import answer, _extract_ingredients
from gaps import detect_gap, log_gap, read_gaps
from transcribe import SUPPORTED_TYPES, TranscriptionError, has_api_key, transcribe

# ── Admin authentication ────────────────────────────────────────────────────────
def _check_admin_auth() -> bool:
    """Return True if user is authenticated for admin view."""
    if "admin_authenticated" not in st.session_state:
        st.session_state.admin_authenticated = False

    if st.session_state.admin_authenticated:
        return True

    # Show password prompt
    st.subheader("🔐 Admin Access")
    password = st.text_input("Enter admin password:", type="password", key="admin_pw_input")
    if password:
        admin_pw = os.environ.get("ADMIN_PASSWORD", "edna-gaps-admin")
        if password == admin_pw:
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("❌ Incorrect password. Try again.")
    return False


def _show_admin_view() -> bool:
    """Return True if admin view should be shown (URL param: ?admin=1)."""
    try:
        return st.query_params.get("admin") == "1"
    except (AttributeError, KeyError):
        return False

# ── Page config (mobile-first) ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Conquista la Cocina — Asistente de Edna",
    page_icon="🍳",
    layout="centered",          # narrow column reads well on phones
    initial_sidebar_state="collapsed",
)

# ── Modern, vibrant styling ──────────────────────────────────────────────────────
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap');

      :root {
          --edna-coral:  #D96A4F;
          --edna-tomato: #C25546;
          --edna-amber:  #D9A25A;
          --edna-basil:  #6E9E7F;
          --edna-ink:    #3A2F26;
          --edna-cream:  #F6EFE7;
      }

      /* Global font + warm canvas.
         The emoji families at the end of every stack matter: without them the
         browser renders 🍳 / 👩‍🍳 as empty boxes, because Nunito carries no
         emoji glyphs and there is nothing after it that does. */
      html, body, [class*="css"], .stMarkdown, .stChatMessage p, .stButton > button,
      .stChatMessage li, [data-testid="stChatInput"] textarea, [data-testid="stExpander"] {
          font-family: 'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI',
                       sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji',
                       'Noto Color Emoji', 'Segoe UI Symbol';
      }
      /* Streamlit renders chat avatars and markdown emoji in their own nodes,
         so the fallback has to reach those too. */
      [data-testid="stChatMessageAvatarUser"],
      [data-testid="stChatMessageAvatarAssistant"],
      [data-testid="stMarkdownContainer"], .stCaption, .edna-hero, .edna-badge {
          font-family: 'Nunito', -apple-system, 'Segoe UI', sans-serif,
                       'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji',
                       'Segoe UI Symbol';
      }
      html, body { font-size: 17px; }
      .stApp {
          background:
             radial-gradient(1200px 500px at 100% -10%, #EFDFD1 0%, rgba(239,223,209,0) 55%),
             radial-gradient(1000px 500px at -10% 0%, #EADDD6 0%, rgba(234,221,214,0) 50%),
             var(--edna-cream);
      }
      .block-container { padding-top: 3.5rem; padding-bottom: 7rem; max-width: 820px; }

      /* ── Hero header card ── */
      .edna-hero {
          position: relative;
          border-radius: 26px;
          padding: 1.9rem 1.6rem 1.7rem;
          margin: 0.25rem 0 1.6rem;
          background: linear-gradient(135deg, #C97155 0%, #BC5F5C 55%, #A94E49 100%);
          box-shadow: 0 18px 40px -18px rgba(120,60,52,0.40);
          overflow: hidden;
      }
      .edna-hero::after {
          content: "🍅🧄🌿🫒";
          position: absolute; right: -6px; top: -14px;
          font-size: 3.1rem; opacity: 0.14; letter-spacing: 6px;
          transform: rotate(-8deg);
      }
      .edna-hero h1 {
          font-family: 'Fraunces', Georgia, serif;
          color: #FDF6F0; margin: 0; font-weight: 700;
          font-size: 2.35rem; line-height: 1.15;
          text-shadow: 0 2px 12px rgba(0,0,0,0.16);
      }
      .edna-hero p {
          color: rgba(253,246,240,0.88);
          margin: 0.5rem 0 0; font-size: 1.12rem; font-weight: 600;
      }
      .edna-badge {
          display: inline-block; margin-bottom: 0.7rem;
          background: rgba(255,255,255,0.18);
          color: #FDF6F0; font-weight: 700; font-size: 0.82rem;
          letter-spacing: 0.14em; text-transform: uppercase;
          padding: 0.34rem 0.85rem; border-radius: 999px;
          backdrop-filter: blur(4px);
          border: 1px solid rgba(255,255,255,0.28);
      }

      /* ── Chat bubbles ── */
      .stChatMessage {
          border-radius: 20px;
          padding: 0.5rem 0.6rem;
          box-shadow: 0 8px 22px -18px rgba(58,47,38,0.35);
          border: 1px solid rgba(58,47,38,0.07);
      }
      /* assistant (Edna) — warm cream */
      .stChatMessage:has(img) {
          background: linear-gradient(180deg, #FCF7F1 0%, #F7EEE5 100%);
      }
      /* user — soft coral tint */
      .stChatMessage:not(:has(img)) {
          background: linear-gradient(180deg, #F4E9E1 0%, #EDDFD5 100%);
      }
      .stChatMessage p, .stChatMessage li {
          font-size: 1.12rem; line-height: 1.65; color: var(--edna-ink);
      }
      .stChatMessage strong { color: var(--edna-tomato); }

      /* ── Example-question chips ── */
      div.stButton > button {
          width: 100%;
          text-align: left;
          white-space: normal;
          height: auto;
          padding: 0.85rem 1.1rem;
          border-radius: 16px;
          line-height: 1.4;
          font-weight: 600;
          font-size: 1.08rem;
          color: var(--edna-ink);
          background: #FCF7F1;
          border: 1.5px solid #E3CDBE;
          box-shadow: 0 6px 16px -14px rgba(160,90,70,0.5);
          transition: transform .12s ease, box-shadow .12s ease, border-color .12s ease, background .12s ease;
      }
      div.stButton > button:hover {
          transform: translateY(-2px);
          border-color: var(--edna-coral);
          background: linear-gradient(180deg, #FCF7F1 0%, #F5E8DF 100%);
          box-shadow: 0 12px 22px -14px rgba(160,90,70,0.55);
          color: var(--edna-tomato);
      }
      div.stButton > button:active { transform: translateY(0); }

      .edna-prompt-label {
          font-weight: 800; color: var(--edna-ink);
          font-size: 1.15rem; margin: 0.4rem 0 0.6rem;
          display: flex; align-items: center; gap: 0.5rem;
      }
      .edna-prompt-label::before {
          content: "✨"; font-size: 1.2rem;
      }

      /* ── Chat input ── */
      [data-testid="stChatInput"] {
          border-radius: 18px;
          border: 1.5px solid #E0C9B9;
          box-shadow: 0 10px 30px -20px rgba(160,90,70,0.6);
          background: #FCF7F1;
      }
      [data-testid="stChatInput"] textarea { font-size: 1.1rem; line-height: 1.5; }
      [data-testid="stChatInput"]:focus-within {
          border-color: var(--edna-coral);
          box-shadow: 0 12px 34px -18px rgba(160,90,70,0.7);
      }

      /* ── Voice-message panel ── */
      [data-testid="stExpander"] {
          border-radius: 18px;
          border: 1.5px solid #E0C9B9;
          background: #FCF7F1;
          box-shadow: 0 8px 22px -20px rgba(160,90,70,0.5);
          overflow: hidden;
      }
      [data-testid="stExpander"] summary {
          font-weight: 700; font-size: 1.06rem; color: var(--edna-ink);
      }
      [data-testid="stExpander"] summary:hover { color: var(--edna-tomato); }
      [data-testid="stAudioInput"] {
          border-radius: 14px;
          border: 1.5px solid #E3CDBE;
          background: #FFFDFB;
      }
      .edna-draft-label {
          font-weight: 800; color: var(--edna-ink);
          font-size: 1.06rem; margin: 1rem 0 0.1rem;
          display: flex; align-items: center; gap: 0.45rem;
      }
      .edna-draft-label::before { content: "📝"; }
      [data-testid="stForm"] {
          border-radius: 16px;
          border: 1.5px solid #E3CDBE;
          background: #FFFDFB;
      }
      [data-testid="stForm"] textarea {
          font-size: 1.08rem; line-height: 1.5; color: var(--edna-ink);
      }

      /* Hide default Streamlit header/footer chrome for a cleaner look */
      #MainMenu, footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

WELCOME = (
    "¡Hola! 👩‍🍳 Soy **Edna**, tu guía en *Conquista la Cocina*.\n\n"
    "Estoy aquí para acompañarte mientras cocinas. Puedes preguntarme:\n\n"
    "- 🥘 **Qué cocinar** con los ingredientes que tengas en casa\n"
    "- ⏱️ **Cuál receta es la más rápida** o cuánto tiempo toma\n"
    "- 🧂 **Técnicas y el porqué de las cosas** — los cuatro pilares: "
    "*sal, grasa, ácido y calor*\n\n"
    "Escríbeme abajo, toca una de las preguntas de ejemplo, o **mándame un mensaje de voz** 🎤 "
    "si tienes las manos ocupadas. ¡Vamos a cocinar algo delicioso! 🍅"
)

EXAMPLES = [
    "Tengo pollo y tomate, ¿qué hago?",
    "Tengo 20 minutos, ¿qué receta puedo preparar?",
    "¿Cuál receta es la más rápida?",
    "¿Cuánta sal uso para carne?",
    "¿Qué ensalada puedo hacer y por qué lleva ácido?",
]

# ── Session state ─────────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []          # list of {"role", "content"}
if "pending" not in st.session_state:
    st.session_state.pending = None         # question awaiting an answer
if "pending_voice" not in st.session_state:
    st.session_state.pending_voice = False  # was the pending question spoken?
if "heard_audio" not in st.session_state:
    # Fingerprints of clips already transcribed. The audio widgets keep returning
    # the same clip on every rerun, so without this each one would be sent to
    # Whisper — and answered — over and over.
    st.session_state.heard_audio = set()
if "draft" not in st.session_state:
    st.session_state.draft = None            # transcript awaiting confirmation


def submit(question: str, voice: bool = False) -> None:
    """Queue a user question for processing on the next rerun."""
    st.session_state.pending = question
    st.session_state.pending_voice = voice


def handle_audio(clip) -> None:
    """Transcribe a clip once and stage it as an editable draft for review."""
    if clip is None:
        return

    data = clip.getvalue()
    fingerprint = hashlib.sha1(data).hexdigest()
    if fingerprint in st.session_state.heard_audio:
        return
    st.session_state.heard_audio.add(fingerprint)

    with st.spinner("Escuchando tu mensaje… 🎧"):
        try:
            text = transcribe(data, filename=getattr(clip, "name", "pregunta.wav"))
        except TranscriptionError as e:
            st.warning(str(e))
            return

    st.session_state.draft = text
    st.rerun()


# ── Admin view ──────────────────────────────────────────────────────────────────
if _show_admin_view():
    if not _check_admin_auth():
        st.stop()  # Stop if not authenticated

    st.title("📊 Admin: Query Gaps")
    st.markdown("**Most recent gaps (knowledge base misses)**")

    gaps = read_gaps(limit=100)
    if not gaps:
        st.info("No gaps logged yet.")
    else:
        st.markdown(f"**Total gaps: {len(gaps)}**")

        # Display as a table
        gap_rows = []
        for g in gaps:
            gap_rows.append({
                "Time": g.get("timestamp", "").replace("T", " ").split(".")[0],
                "Question": g.get("question", "")[:80],
                "Route": g.get("route", ""),
                "Recipes": g.get("recipes_found", 0),
                "Theory": g.get("theory_found", 0),
                "Reason": g.get("reason", ""),
                "Reply": g.get("reply_excerpt", "")[:100],
            })

        st.dataframe(gap_rows, use_container_width=True, hide_index=True)

        # Export button
        import json
        export_text = "\n".join(json.dumps(g, ensure_ascii=False) for g in gaps)
        st.download_button(
            "📥 Download gaps as JSONL",
            export_text,
            file_name="gaps.jsonl",
            mime="text/plain",
        )

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚪 Logout"):
            st.session_state.admin_authenticated = False
            st.rerun()
    with col2:
        st.markdown("*Remove `?admin=1` from URL to return to main app.*")
    st.stop()  # Don't show the main app

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div class="edna-hero">
      <span class="edna-badge">👩‍🍳 Asistente de cocina</span>
      <h1>🍳 Conquista la Cocina</h1>
      <p>Con Edna Cochez · tu maestra de cocina</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Welcome + example questions (only before the first exchange) ─────────────────
if not st.session_state.messages and st.session_state.pending is None:
    with st.chat_message("assistant", avatar="👩‍🍳"):
        st.markdown(WELCOME)

    st.write("")
    st.markdown(
        '<div class="edna-prompt-label">Prueba con una de estas preguntas</div>',
        unsafe_allow_html=True,
    )
    for i, ex in enumerate(EXAMPLES):
        st.button(ex, key=f"ex_{i}", on_click=submit, args=(ex,))

# ── Render chat history ──────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    avatar = "👩‍🍳" if msg["role"] == "assistant" else None
    with st.chat_message(msg["role"], avatar=avatar):
        if msg.get("voice"):
            st.caption("🎤 Mensaje de voz")
        st.markdown(msg["content"])

# ── Voice input ──────────────────────────────────────────────────────────────────
# The `expanded` flag is deliberately constant: changing it between reruns
# remounts the panel, which aborts an in-flight recording upload and makes the
# widget show "An error has occurred". The transcript is confirmed below instead.
with st.container(key="voice_input_container"):
    with st.expander("🎤 Prefiero hablar — enviar un mensaje de voz", expanded=False):
        if not has_api_key():
            st.info(
                "Los mensajes de voz necesitan una clave de OpenAI. "
                "Configura `OPENAI_API_KEY` para activarlos."
            )
        else:
            st.caption("Graba tu pregunta y Edna la escuchará. Habla con normalidad.")
            recorded = st.audio_input("Grabar", key="voice_rec", label_visibility="collapsed")
            handle_audio(recorded)

            # The recorder shows a generic "An error has occurred" when the browser
            # finds no microphone, which tells the customer nothing — explain it and
            # point at the upload option, which needs no mic.
            st.caption(
                "¿Ves un error al grabar? Significa que tu dispositivo no tiene "
                "micrófono disponible. Puedes subir un audio en su lugar 👇"
            )

            st.caption("O sube un audio que ya tengas grabado:")
            uploaded = st.file_uploader(
                "Subir audio",
                type=SUPPORTED_TYPES,
                key="voice_file",
                label_visibility="collapsed",
            )
            handle_audio(uploaded)

# ── Confirm / correct the transcript before spending an answer on it ─────────────
# Rendered outside the expander so it is always visible and so the recorder
# above it is never remounted by this block appearing or disappearing.
if st.session_state.draft is not None:
    st.markdown('<div class="edna-draft-label">Esto escuché</div>',
                unsafe_allow_html=True)
    with st.form("voice_confirm", clear_on_submit=False):
        edited = st.text_area(
            "Revisa y corrige si hace falta, luego envía tu pregunta:",
            value=st.session_state.draft,
            height=120,
            key="draft_text",
        )
        col_send, col_drop = st.columns(2)
        send = col_send.form_submit_button(
            "✅ Enviar a Edna", use_container_width=True, type="primary"
        )
        drop = col_drop.form_submit_button(
            "🗑️ Descartar", use_container_width=True
        )

    if send:
        question = edited.strip()
        if question:
            st.session_state.draft = None
            submit(question, voice=True)
            st.rerun()
        else:
            st.warning("El mensaje está vacío. Graba de nuevo o escribe tu pregunta.")
    elif drop:
        st.session_state.draft = None
        st.rerun()

# ── Chat input ───────────────────────────────────────────────────────────────────
typed = st.chat_input("Escribe tu pregunta de cocina…")
if typed:
    submit(typed)

# ── Process a pending question ───────────────────────────────────────────────────
if st.session_state.pending:
    question = st.session_state.pending
    was_voice = st.session_state.pending_voice
    st.session_state.pending = None
    st.session_state.pending_voice = False

    # Echo the user's question — voice messages show what Whisper heard,
    # so the customer can tell a wrong answer from a wrong transcription.
    st.session_state.messages.append(
        {"role": "user", "content": question, "voice": was_voice}
    )
    with st.chat_message("user"):
        if was_voice:
            st.caption("🎤 Mensaje de voz")
        st.markdown(question)

    # Generate Edna's answer
    with st.chat_message("assistant", avatar="👩‍🍳"):
        with st.spinner("Edna está pensando… 🍲"):
            ings = _extract_ingredients(question)
            try:
                result = answer(question, ings)
                reply = result["reply"]
                metadata = result["metadata"]
            except Exception as e:  # surface API/network issues kindly
                reply = (
                    "¡Ay! Tuve un problemita para responderte en este momento. 😔 "
                    "Por favor intenta de nuevo en unos segundos.\n\n"
                    f"<small>Detalle técnico: {e}</small>"
                )
                metadata = {"route": "error", "recipes_found": 0, "theory_found": 0}

        # Detect and log gaps
        gap = detect_gap(
            question=question,
            route_type=metadata["route"],
            num_recipes=metadata["recipes_found"],
            num_theory=metadata["theory_found"],
            reply=reply,
        )
        if gap:
            log_gap(gap)

        st.markdown(reply, unsafe_allow_html=True)

    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()

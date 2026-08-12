"""
transcribe.py — voice-message transcription for the Edna assistant

Turns a recorded or uploaded audio clip into Spanish text with OpenAI's
Whisper API, so the customer can ask by voice instead of typing.

Usage:
  from transcribe import transcribe, TranscriptionError
  text = transcribe(audio_bytes, filename="pregunta.wav")

CLI check:
  python transcribe.py ruta/al/audio.m4a
"""

import os
import sys

from openai import OpenAI

# whisper-1 is the classic Whisper endpoint and handles Spanish natively.
# "gpt-4o-transcribe" is a drop-in swap here if you want lower word-error rate.
MODEL = "whisper-1"

# The API rejects uploads over 25 MB — catch it before the round trip.
MAX_BYTES = 25 * 1024 * 1024

# Pinning the language stops Whisper from guessing wrong on short clips
# ("¿Cuánta sal?" is brief enough to be mistaken for Portuguese/Italian).
LANGUAGE = "es"

# Biases the decoder toward the vocabulary of this course, so recipe names and
# cooking terms come back spelled correctly instead of phonetically.
_PROMPT = (
    "Pregunta de cocina en español para el curso Conquista la Cocina de Edna Cochez. "
    "Vocabulario habitual: sal, grasa, ácido, calor, sofreír, escalfar, sellar, "
    "marinar, emulsionar, pechuga de pollo, ajo, tomate, cebolla, aceite de oliva, "
    "vinagre, limón, sartén, plancha, horno, receta, ingredientes, porciones."
)

# Formats the Whisper endpoint accepts.
SUPPORTED_TYPES = ["wav", "mp3", "m4a", "ogg", "webm", "mp4", "mpga", "mpeg", "flac"]


class TranscriptionError(RuntimeError):
    """Raised with a customer-friendly Spanish message when transcription fails."""


# ── Hallucination guard ────────────────────────────────────────────────────────
# Fed music, silence or background noise, Whisper does not return empty text —
# it invents fluent boilerplate, often the same sentence over and over (subtitle
# credits are a favourite). Sending that to Edna wastes a call and confuses the
# customer, so reject it before it reaches the chat.

# Above this, the segment is very likely not speech at all.
_NO_SPEECH_LIMIT = 0.6

# Below this, Whisper had little confidence in the words it chose.
_LOGPROB_LIMIT = -1.0


def _is_hallucination(text: str, segments=None) -> bool:
    """True when the transcript looks invented rather than spoken."""
    import re

    # A real question is not the same sentence repeated. Compare unique
    # sentences against the total; heavy repetition is the classic tell.
    sentences = [s.strip().lower() for s in re.split(r"[.!?¿¡\n]+", text) if s.strip()]
    if len(sentences) >= 3 and len(set(sentences)) / len(sentences) <= 0.4:
        return True

    if not segments:
        return False

    # Trust the model's own confidence: if most of the clip reads as non-speech
    # or very low probability, treat the whole transcript as noise.
    no_speech = [
        s for s in segments
        if (getattr(s, "no_speech_prob", 0) or 0) > _NO_SPEECH_LIMIT
        or (getattr(s, "avg_logprob", 0) or 0) < _LOGPROB_LIMIT
    ]
    return len(no_speech) > len(segments) / 2


# ── API key ────────────────────────────────────────────────────────────────────

def _load_api_key() -> str:
    """Read OPENAI_API_KEY from the environment, falling back to the .env file.

    Same two-step lookup answer.py uses for ANTHROPIC_API_KEY.
    """
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        for line in open(".env", encoding="utf-8-sig"):
            if line.strip().startswith("OPENAI_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def has_api_key() -> bool:
    """True when a key is available, so the UI can hide voice input if not."""
    return bool(_load_api_key())


# ── Transcription ──────────────────────────────────────────────────────────────

def transcribe(audio: bytes, filename: str = "pregunta.wav") -> str:
    """Transcribe a Spanish audio clip and return the text.

    audio:    raw bytes of the recording or uploaded file
    filename: name (with extension) so the API can infer the container format

    Raises TranscriptionError with a message safe to show the customer.
    """
    if not audio:
        raise TranscriptionError("No recibí ningún audio. Intenta grabar de nuevo.")

    if len(audio) > MAX_BYTES:
        mb = len(audio) / (1024 * 1024)
        raise TranscriptionError(
            f"El audio es muy grande ({mb:.1f} MB). El límite es 25 MB — "
            "graba un mensaje más corto."
        )

    key = _load_api_key()
    if not key:
        raise TranscriptionError(
            "Falta la clave de OpenAI. Configura la variable de entorno "
            "OPENAI_API_KEY para activar los mensajes de voz."
        )

    client = OpenAI(api_key=key)
    try:
        result = client.audio.transcriptions.create(
            model=MODEL,
            file=(filename, audio),
            language=LANGUAGE,
            prompt=_PROMPT,
            # verbose_json exposes per-segment confidence, which is the only way
            # to tell real speech from Whisper's hallucinations on music/silence.
            response_format="verbose_json",
            temperature=0,
        )
    except Exception as e:
        # Auth and quota problems are configuration mistakes, not transient
        # failures — say so plainly instead of telling the customer to retry.
        status = getattr(e, "status_code", None)
        if status == 401:
            raise TranscriptionError(
                "La clave de OpenAI no es válida (401). Genera una nueva en "
                "platform.openai.com/api-keys y actualiza OPENAI_API_KEY."
            ) from e
        if status == 429:
            raise TranscriptionError(
                "La cuenta de OpenAI no tiene crédito disponible (429). "
                "Agrega saldo en platform.openai.com/settings/organization/billing."
            ) from e
        raise TranscriptionError(
            f"No pude transcribir el audio en este momento. Detalle: {e}"
        ) from e

    text = (result.text or "").strip()
    if not text:
        raise TranscriptionError(
            "No escuché nada en la grabación. Acércate al micrófono e intenta de nuevo."
        )

    if _is_hallucination(text, getattr(result, "segments", None)):
        raise TranscriptionError(
            "No reconocí ninguna pregunta en ese audio — puede que sea música o "
            "ruido. Graba tu pregunta hablando con normalidad e intenta de nuevo."
        )
    return text


# ── Key check ──────────────────────────────────────────────────────────────────

def _silent_clip() -> bytes:
    """Build a one-second WAV in memory, so the key check needs no audio file."""
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<h", 0) * 16000)
    return buf.getvalue()


def check_key() -> tuple[bool, str]:
    """Verify the configured key end to end. Returns (ok, human-readable message).

    Sends a generated silent clip, so it exercises the real Whisper endpoint —
    auth, billing and model access — without needing a recording on disk.
    """
    key = _load_api_key()
    if not key:
        return False, (
            "No encontré ninguna clave. Define OPENAI_API_KEY en el entorno "
            "o agrégala al archivo .env."
        )

    source = "variable de entorno" if os.environ.get("OPENAI_API_KEY", "").strip() else ".env"
    where = f"Clave encontrada en {source} (termina en …{key[-4:]}, {len(key)} caracteres)."

    try:
        OpenAI(api_key=key).audio.transcriptions.create(
            model=MODEL,
            file=("check.wav", _silent_clip()),
            language=LANGUAGE,
        )
    except TranscriptionError:
        raise
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status == 401:
            return False, (
                f"{where}\nLa clave NO es válida (401). Genera una nueva en "
                "https://platform.openai.com/api-keys y reemplaza el valor.\n"
                "Si acabas de crearla, confirma que estás en la misma "
                "organización/proyecto donde tienes el crédito."
            )
        if status == 429:
            return False, (
                f"{where}\nLa clave es válida, pero la cuenta no tiene crédito (429). "
                "Agrega saldo en "
                "https://platform.openai.com/settings/organization/billing."
            )
        return False, f"{where}\nFalló la verificación: {e}"

    # Silence transcribes to empty text — reaching this point means the request
    # was accepted, which is exactly what we set out to prove.
    return True, f"{where}\n¡Todo listo! La transcripción de voz está funcionando."


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = sys.argv[1:]

    # No arguments (or --check): verify the API key, no audio file needed.
    if not args or args[0] in ("--check", "-c"):
        ok, message = check_key()
        print(message)
        sys.exit(0 if ok else 1)

    path = args[0]
    if not os.path.exists(path):
        print(f"No existe el archivo: {path}")
        print("\nUso:")
        print("  python transcribe.py            → verifica la clave de OpenAI")
        print("  python transcribe.py audio.m4a  → transcribe un audio real")
        sys.exit(1)

    with open(path, "rb") as fh:
        data = fh.read()

    try:
        print(transcribe(data, filename=os.path.basename(path)))
    except TranscriptionError as e:
        print(f"Error: {e}")
        sys.exit(1)

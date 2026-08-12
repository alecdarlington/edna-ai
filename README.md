# Edna AI — Cooking Intelligence

A Streamlit app that combines Edna Cochez's recipes and cooking education with AI-powered search, voice input, and personalized cooking guidance.

## Features

- **Recipe Search**: Find dishes based on pantry ingredients, time constraints, or dish type
- **Voice Input**: Record or upload Spanish cooking questions via Whisper transcription
- **Educational Content**: Learn cooking pillars (heat, fat, acid, salt) and techniques
- **Smart Routing**: Distinguishes between recipe requests, technique questions, and hybrid queries

## Data

- **177 recipes** across 14 categories (mains, sides, breakfast, sauces, etc.)
- **221 educational chunks** on cooking fundamentals and techniques
- **Spanish-optimized** ingredient normalization and voice transcription

## Setup

### Prerequisites

- Python 3.9+
- [Claude API key](https://console.anthropic.com)
- [OpenAI API key](https://platform.openai.com/api-keys) (for Whisper)

### Local Development

```bash
pip install -r requirements.txt
streamlit run app.py
```

Visit `http://localhost:8501` in your browser.

### Environment Variables

Create a `.env` file (or use Streamlit Cloud's Secrets):

```
ANTHROPIC_API_KEY=your-claude-key-here
OPENAI_API_KEY=your-openai-key-here
```

## Deployment

Deploy to [Streamlit Community Cloud](https://streamlit.io/cloud):

1. Push this repo to GitHub
2. Connect via Streamlit Cloud dashboard
3. Add secrets via `Settings → Secrets` (do NOT add to code)

## Architecture

- **app.py** — Streamlit UI
- **answer.py** — Edna persona and response generation
- **search.py** — Ingredient/name/category recipe search
- **theory.py** — Educational pillar lookup
- **recipes.json** — Recipe database
- **theory.json** — Educational chunks

## License

Private project. Data from Edna Cochez.

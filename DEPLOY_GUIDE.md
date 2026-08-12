# Edna AI — Deployment to Streamlit Community Cloud

## STEP 1: Initialize Git & Commit Code

Run these commands in your terminal:

```bash
cd c:\Users\darli\Desktop\edna-ai
git init
git add .
git commit -m "Initial commit: Edna AI Streamlit app"
```

---

## STEP 2: Create GitHub Repository

1. Go to **https://github.com/new**
2. Fill in the form:
   - **Repository name:** `edna-ai`
   - **Description:** "Cooking intelligence with AI recipes and voice input"
   - **Visibility:** Select **PUBLIC** (required for free Streamlit Cloud)
   - Leave other options as default
3. Click **"Create repository"** button

---

## STEP 3: Connect Local Repo to GitHub

GitHub will show you commands on the next screen. Copy and run these:

```bash
git remote add origin https://github.com/YOUR_USERNAME/edna-ai.git
git branch -M main
git push -u origin main
```

**Important:** Replace `YOUR_USERNAME` with your actual GitHub username.

Example:
```bash
git remote add origin https://github.com/darlingtonalec/edna-ai.git
git branch -M main
git push -u origin main
```

---

## STEP 4: Deploy to Streamlit Community Cloud

1. Go to **https://share.streamlit.io**
2. Sign in with your GitHub account
3. Click **"New app"** button
4. In the form, select:
   - **GitHub repo:** `YOUR_USERNAME/edna-ai`
   - **Branch:** `main`
   - **Main file path:** `app.py`
5. Click **"Deploy"** button
6. Wait 1-2 minutes for deployment to complete
7. You'll get a public URL: **https://edna-ai.streamlit.app**

---

## STEP 5: Add API Keys (SECRETS ONLY — Never in Code)

**CRITICAL:** API keys go ONLY in Streamlit Cloud's Secrets, NOT in your code or .env file.

1. On your deployed app (at https://edna-ai.streamlit.app), click the **⋮ (three dots)** menu in the top right
2. Select **"Settings"**
3. Click the **"Secrets"** tab on the left
4. Paste your API keys exactly (one per line):

```
ANTHROPIC_API_KEY = "sk-ant-v1-YOUR_CLAUDE_KEY_HERE"
OPENAI_API_KEY = "sk-org-YOUR_OPENAI_KEY_HERE"
```

Replace the placeholder values with your actual API keys:
- Get Claude key from: https://console.anthropic.com/account/keys
- Get OpenAI key from: https://platform.openai.com/api-keys

5. Click **"Save"** button
6. Streamlit will automatically restart your app with the secrets loaded

---

## STEP 6: Test the Live App

1. Visit your deployed app: **https://edna-ai.streamlit.app**
2. Try these tests:
   - Ask a recipe question in Spanish: **"Tengo pollo y tomate, ¿qué receta puedo hacer?"**
   - Record or upload a voice message to test Whisper transcription
   - Search for recipes by ingredient
   - Try a theory question: **"¿Cuál es la importancia del ácido en la cocina?"**

3. If you get API errors:
   - Check that both API keys are correctly added in Secrets
   - Wait a few seconds for the app to restart after adding keys
   - Refresh the page

---

## Done!

Your Edna AI app is now live on the public internet with:
- ✅ Full recipe search functionality
- ✅ Voice input via Whisper
- ✅ Educational content on cooking pillars
- ✅ Secure API keys (NOT in public code)
- ✅ Public URL anyone can access

## Files Prepared for You

These files are already in your project directory:
- `requirements.txt` — Python dependencies
- `README.md` — Project documentation
- `.gitignore` — Protects secrets from being committed
- `.streamlit/config.toml` — Styling and Streamlit configuration

## Troubleshooting

**App won't start:**
- Check that `requirements.txt` lists all dependencies
- Verify `app.py` is in the root directory

**API errors (401, invalid_api_key):**
- Go to Settings → Secrets
- Paste your full API key (including the `sk-ant-v1-` or `sk-org-` prefix)
- Click Save and wait 10 seconds

**Secrets not loading:**
- Refresh the page with Ctrl+Shift+R (hard refresh)
- Wait 30 seconds after clicking Save

**Voice input not working:**
- Make sure OPENAI_API_KEY is set in Secrets
- Test with a short 3-5 second recording first

---

## Your Public URL

Once deployed, share this link: **https://edna-ai.streamlit.app**

Anyone can visit and ask Edna questions about recipes and cooking!

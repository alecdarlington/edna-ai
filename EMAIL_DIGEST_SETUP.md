# Email Digest Setup Guide (Gmail)

The Edna AI app sends daily digests summarizing:
- Knowledge gaps detected
- Query statistics
- Route distribution
- Sample queries

**This guide uses Gmail (free, no credit card needed)**

---

## Step 1: Enable 2-Step Verification on Gmail

1. Go to **https://myaccount.google.com/security**
2. Look for **2-Step Verification**
3. If not enabled:
   - Click **2-Step Verification**
   - Follow the prompts to verify your phone number
   - Enable it

## Step 2: Generate Gmail App Password

1. Go to **https://myaccount.google.com/apppasswords**
2. Select:
   - **App**: Mail
   - **Device**: Windows Computer (or your device)
3. Click **Generate**
4. Google will show a **16-character password** (with spaces)
5. **Copy it exactly** (e.g., `abcd efgh ijkl mnop`)
   - ⚠️ Copy the whole thing including spaces!

## Step 3: Add to Streamlit Cloud Secrets

Go to your Streamlit app → **Settings** → **Secrets** → Add:

```
GMAIL_EMAIL = "darlingtonalec@gmail.com"
GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"
ADMIN_EMAIL = "darlingtonalec@gmail.com"
```

Replace with your actual Gmail address and the App Password you just generated.

Click **Save**.

The app will restart automatically.

## Step 4: Test the Digest

1. Wait 2 minutes for Streamlit to redeploy
2. Go to **https://edna-ai.streamlit.app/?admin=1**
3. Log in with your admin password
4. Scroll to **📧 Email Digest** section
5. Click **📤 Send Digest Now**
6. Check your inbox in ~10 seconds

✅ If successful: "Digest sent to your@email.com"
❌ If it fails: Check the error message

## Step 5: Set Up Daily Automatic Emails (Optional)

You can send digests automatically every day using GitHub Actions.

### Setup GitHub Actions Workflow

1. Create a new file: `.github/workflows/daily-digest.yml`
2. Paste this:

```yaml
name: Send Daily Digest

on:
  schedule:
    - cron: '0 9 * * *'  # 9 AM UTC every day

jobs:
  send-digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - run: pip install -r requirements.txt
      - run: python -c "from email_digest import send_digest_email; result = send_digest_email(); print(result['message'])"
        env:
          GMAIL_EMAIL: ${{ secrets.GMAIL_EMAIL }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          ADMIN_EMAIL: ${{ secrets.ADMIN_EMAIL }}
```

3. Add the same secrets to GitHub:
   - Go to your repo → **Settings** → **Secrets and variables** → **Actions**
   - Add: `GMAIL_EMAIL`, `GMAIL_APP_PASSWORD`, `ADMIN_EMAIL`
4. Push the workflow file to main branch
5. GitHub will run it automatically every day at 9 AM UTC

---

## Email Contents

The daily digest includes:

- **📊 Summary**: Total queries, gaps detected, avg recipes/theory found
- **🎯 Route Breakdown**: % of recipe vs technique questions
- **⚠️ Knowledge Gaps**: Questions where AI had no relevant content
- **🔍 Sample Queries**: Recent questions from that day

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Missing Gmail credentials" | Add both GMAIL_EMAIL and GMAIL_APP_PASSWORD to Streamlit Secrets |
| "Gmail authentication failed" | You used your regular Gmail password instead of App Password. Get a new one from myaccount.google.com/apppasswords |
| Email not received | Check spam folder; try sending to a different email address |
| "2-Step Verification required" | Enable 2-Step Verification at myaccount.google.com/security first |
| App Password not working | Make sure you copied the spaces correctly (e.g., `abcd efgh ijkl mnop`) |

---

## Customizing the Digest

Edit `email_digest.py` to change:
- Number of gaps shown: `today_gaps[-10:]` (change 10)
- Number of queries shown: `queries[-5:]` (change 5)
- Email styling: Modify the HTML in `build_digest_html()`
- Send time: Change `cron: '0 9 * * *'` in the workflow (currently 9 AM UTC)

---

## Security Notes

- Your Gmail App Password is specific to this app only
- It can ONLY send emails; it can't access your Gmail account
- If compromised, you can revoke it from myaccount.google.com/apppasswords
- Never commit App Password to GitHub—always use Streamlit Secrets

---

**You're all set!** You'll now get daily digests of Edna's performance. 🍳

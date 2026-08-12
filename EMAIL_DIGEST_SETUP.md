# Email Digest Setup Guide

The Edna AI app can send daily digests summarizing:
- Knowledge gaps detected
- Query statistics
- Route distribution
- Sample queries

## About SendGrid + Twilio

**SendGrid is now part of Twilio** (acquired in 2019). The good news: the SendGrid email API is unchanged and still free. You just manage it through the Twilio Console now.

- **Twilio Console**: https://www.twilio.com/console/sendgrid
- **SendGrid API**: Still works exactly the same (v3 REST API)
- **Free tier**: Still available (100 emails/day)
- **No changes needed**: If you already have a SendGrid account, just log in with your existing credentials

---

## Step 1: Create SendGrid Account (via Twilio)

1. Go to **https://www.twilio.com/console/sendgrid/apps** (Twilio/SendGrid Console)
2. Or sign up at **https://sendgrid.com/free** (redirects to Twilio)
3. Sign up with your email
4. Verify your email address
5. Log in to the Twilio Console

## Step 2: Generate API Key

1. In Twilio Console, go to **SendGrid** → **Settings** → **API Keys**
2. Click **Create API Key** (blue button)
3. Name it: `edna-ai-digest`
4. Keep permissions as **Restricted Access**
5. Enable only: **Mail Send**
6. Click **Create & View**
7. **Copy the key** (it looks like `SG.xxxxxxxxxxxxx`)
   - ⚠️ You can only see it once! Copy it now.
8. Save it somewhere safe

## Step 3: Verify Sender Email

1. In Twilio Console, go to **SendGrid** → **Sender Authentication**
2. Click **Verify a Sender**
3. Enter:
   - **From Name**: `Edna AI`
   - **From Email**: Your email (e.g., `darlingtonalec@gmail.com`)
   - **Reply To Email**: Same email
4. Click **Create**
5. Check your email inbox for a verification link from SendGrid/Twilio
6. Click the link to verify
7. ✅ Status should show "Verified"

## Step 4: Add Secrets to Streamlit Cloud

Go to your Streamlit app → **Settings** → **Secrets** → Add:

```
SENDGRID_API_KEY = "SG.your_api_key_here"
SENDGRID_FROM_EMAIL = "darlingtonalec@gmail.com"
ADMIN_EMAIL = "darlingtonalec@gmail.com"
```

Replace with your actual values. Click **Save**.

The app will restart automatically.

## Step 5: Test the Digest

1. Wait 2 minutes for the app to redeploy
2. Go to **https://edna-ai.streamlit.app/?admin=1**
3. Log in with your admin password
4. Scroll to **📧 Email Digest** section
5. Click **📤 Send Digest Now**
6. You should get an email in ~30 seconds

✅ If successful: "Digest sent to your@email.com"
❌ If it fails: Check the error message (usually missing credentials)

## Step 6: Set Up Daily Automatic Emails

### Option A: Streamlit Secrets + Cron Job (Recommended)

You can add a scheduled task that runs daily. There are several ways:

**Using GitHub Actions** (easiest):
1. Create `.github/workflows/daily-digest.yml`:

```yaml
name: Send Daily Digest

on:
  schedule:
    - cron: '0 9 * * *'  # 9 AM UTC every day

jobs:
  send-digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - run: pip install -r requirements.txt
      - run: python -c "from email_digest import send_digest_email; send_digest_email()"
        env:
          SENDGRID_API_KEY: ${{ secrets.SENDGRID_API_KEY }}
          SENDGRID_FROM_EMAIL: ${{ secrets.SENDGRID_FROM_EMAIL }}
          ADMIN_EMAIL: ${{ secrets.ADMIN_EMAIL }}
```

2. Add secrets to your GitHub repo:
   - Go to Settings → Secrets and variables → Actions
   - Add `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, `ADMIN_EMAIL`

3. Save and push. Workflow will run automatically every day at 9 AM UTC.

**Using Vercel Cron** (if you deploy elsewhere):
- Similar setup with cron endpoints

### Option B: Manual Daily Reminder

Just visit admin → **Send Digest Now** each day.

## Digest Contents

The email includes:
- **Summary Stats**: Total queries, gaps, avg recipe/theory count
- **Route Distribution**: Recipe % vs Technique % queries
- **Knowledge Gaps**: Questions where AI had no relevant content
- **Sample Queries**: Recent questions asked

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Missing SendGrid credentials" | Add all 3 env vars to Streamlit Secrets |
| Email not received | Check spam folder; verify sender email is verified in Twilio Console |
| Error 401 (Unauthorized) | API key is wrong or expired; regenerate it from Twilio Console |
| Error 403 (Forbidden) | API key doesn't have "Mail Send" permission; regenerate with restricted access |
| "Invalid email address" | Sender email not verified in Twilio Console SendGrid settings |
| Can't find SendGrid settings | Use **https://www.twilio.com/console/sendgrid** directly |

## Email Customization

Edit `email_digest.py`:
- Change `today_gaps[-10:]` to show more/fewer gaps
- Change `queries[-5:]` to show more/fewer sample queries
- Modify HTML styling in `build_digest_html()`
- Add more statistics by querying `read_activity()` and `read_gaps()`

---

**Next**: Once set up, check your email daily for insights into how Edna is performing!

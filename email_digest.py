"""
email_digest.py — Daily digest of gaps and AI responses

Sends a summary email of:
- Knowledge base gaps detected
- Statistics on AI responses
- Top queries

Uses Gmail SMTP (free, no credit card needed)
"""

import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from gaps import read_gaps, read_activity


def _get_secret(key: str) -> str:
    """Get secret from Streamlit Cloud or environment variables."""
    try:
        import streamlit as st
        return st.secrets.get(key, "").strip()
    except (ImportError, AttributeError):
        return os.environ.get(key, "").strip()


GMAIL_EMAIL = _get_secret("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = _get_secret("GMAIL_APP_PASSWORD")
ADMIN_EMAIL = _get_secret("ADMIN_EMAIL")


def _get_today_start() -> str:
    """Get ISO timestamp for start of today (UTC)."""
    return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _filter_by_date(records: list[dict], since_iso: str) -> list[dict]:
    """Filter records by timestamp >= since_iso."""
    return [r for r in records if r.get("timestamp", "") >= since_iso]


def build_digest_html() -> str:
    """Build HTML email body with gaps and response stats."""
    today_start = _get_today_start()

    # Get today's gaps
    all_gaps = read_gaps(limit=1000)
    today_gaps = _filter_by_date(all_gaps, today_start)

    # Get today's activities
    all_activities = read_activity(limit=5000)
    today_activities = _filter_by_date(all_activities, today_start)

    # Filter for responses and queries
    responses = [a for a in today_activities if a.get("event_type") == "response"]
    queries = [a for a in today_activities if a.get("event_type") == "query"]

    # Statistics
    total_queries = len(queries)
    total_gaps = len(today_gaps)
    avg_route_type = {}
    recipes_found_avg = 0
    theory_found_avg = 0

    if responses:
        for r in responses:
            route = r.get("route", "unknown")
            avg_route_type[route] = avg_route_type.get(route, 0) + 1
            recipes_found_avg += r.get("recipes_found", 0)
            theory_found_avg += r.get("theory_found", 0)

        recipes_found_avg = int(recipes_found_avg / len(responses))
        theory_found_avg = int(theory_found_avg / len(responses))

    # Build HTML
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #C97155; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
            .section {{ margin-bottom: 30px; }}
            .section h2 {{ border-bottom: 2px solid #C97155; padding-bottom: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
            th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background: #f5f5f5; font-weight: bold; }}
            .stat {{ background: #f9f9f9; padding: 15px; border-radius: 5px; margin: 10px 0; }}
            .gap-item {{ background: #ffe0e0; padding: 10px; margin: 5px 0; border-radius: 4px; }}
            .query-item {{ background: #e0f0ff; padding: 10px; margin: 5px 0; border-radius: 4px; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #999; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🍳 Edna AI Daily Digest</h1>
                <p>{datetime.utcnow().strftime('%Y-%m-%d')}</p>
            </div>

            <div class="section">
                <h2>📊 Summary</h2>
                <div class="stat">
                    <strong>Total Queries:</strong> {total_queries}<br>
                    <strong>Knowledge Gaps Detected:</strong> {total_gaps}<br>
                    <strong>Avg Recipes Found per Query:</strong> {recipes_found_avg}<br>
                    <strong>Avg Theory Chunks per Query:</strong> {theory_found_avg}
                </div>
            </div>

            <div class="section">
                <h2>🎯 Query Routes</h2>
                <div class="stat">
    """

    for route, count in sorted(avg_route_type.items(), key=lambda x: x[1], reverse=True):
        pct = int((count / len(responses) * 100)) if responses else 0
        html += f"<strong>{route.upper()}:</strong> {count} queries ({pct}%)<br>"

    html += """
                </div>
            </div>
    """

    if today_gaps:
        html += f"""
            <div class="section">
                <h2>⚠️ Knowledge Gaps ({len(today_gaps)})</h2>
                <p><em>Questions where the AI had no relevant content</em></p>
        """
        for gap in today_gaps[-10:]:  # Show last 10
            q = gap.get("question", "")[:100]
            reason = gap.get("reason", "")
            html += f'<div class="gap-item"><strong>Q:</strong> {q}<br><small>Reason: {reason}</small></div>'

        html += "</div>"

    if queries:
        html += f"""
            <div class="section">
                <h2>🔍 Sample Queries ({len(queries)})</h2>
        """
        for query in queries[-5:]:  # Show last 5
            q = query.get("question", "")[:100]
            html += f'<div class="query-item"><strong>Q:</strong> {q}</div>'

        html += "</div>"

    html += """
            <div class="footer">
                <p>This digest was auto-generated by Edna AI at """ + datetime.utcnow().isoformat() + """</p>
                <p>View full logs: https://edna-ai.streamlit.app/?admin=1</p>
            </div>
        </div>
    </body>
    </html>
    """

    return html


def send_digest_email(to_email: str | None = None) -> dict:
    """
    Send digest email via Gmail SMTP (free, no credit card needed).

    Returns: {"success": bool, "message": str}
    """
    if not GMAIL_EMAIL or not GMAIL_APP_PASSWORD:
        return {
            "success": False,
            "message": "Missing Gmail credentials (GMAIL_EMAIL or GMAIL_APP_PASSWORD). "
                       "See EMAIL_DIGEST_SETUP.md for instructions.",
        }

    recipient = to_email or ADMIN_EMAIL
    if not recipient:
        return {"success": False, "message": "No recipient email configured"}

    html_body = build_digest_html()
    subject = f"🍳 Edna AI Daily Digest — {datetime.utcnow().strftime('%Y-%m-%d')}"

    try:
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_EMAIL
        msg["To"] = recipient

        # Attach HTML body
        msg.attach(MIMEText(html_body, "html"))

        # Connect to Gmail SMTP and send
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_EMAIL, recipient, msg.as_string())

        return {
            "success": True,
            "message": f"✅ Digest sent to {recipient}",
        }

    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "message": "Gmail authentication failed. Check your App Password (not your regular password).",
        }
    except smtplib.SMTPException as e:
        return {
            "success": False,
            "message": f"Gmail SMTP error: {str(e)[:150]}",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error sending email: {str(e)[:150]}",
        }

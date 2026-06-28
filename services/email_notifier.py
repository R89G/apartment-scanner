import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from models.listing import Listing

logger = logging.getLogger(__name__)


def send_notification(new_listings: list[Listing], run_stats: dict) -> bool:
    if not new_listings:
        logger.info("No new listings — email not sent")
        return False

    gmail_user = os.environ["GMAIL_USER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]
    sheet_url = run_stats.get("sheet_url", "N/A")

    n = len(new_listings)
    now = datetime.now()
    date_str = now.strftime("%d/%m/%Y")
    time_str = now.strftime("%H:%M")

    old_north_count = sum(1 for l in new_listings if l.is_old_north)
    renovated_count = sum(1 for l in new_listings if l.property_status is not None)
    sites_scanned = run_stats.get("sites_scanned", [])

    subject = f"\U0001f3e0 [{n}] New Apartments Found — Weekly Scan [{date_str}]"

    plain_body = f"""Hi Roy,

The weekly apartment scan completed on {date_str} at {time_str}.

{n} new listings were added to your Google Sheet.

Quick summary:
- Source sites scanned: {', '.join(sites_scanned) if sites_scanned else 'N/A'}
- New listings this week: {n}
- Old North listings: {old_north_count}
- Renovated listings: {renovated_count}

Open your Google Sheet to review:
{sheet_url}

—
Apartment Scanner Bot"""

    html_body = f"""<html><body>
<p>Hi Roy,</p>
<p>The weekly apartment scan completed on <strong>{date_str}</strong> at <strong>{time_str}</strong>.</p>
<p><strong>{n} new listings</strong> were added to your Google Sheet.</p>
<h3>Quick summary</h3>
<ul>
  <li>Source sites scanned: {', '.join(sites_scanned) if sites_scanned else 'N/A'}</li>
  <li>New listings this week: <strong>{n}</strong></li>
  <li>Old North listings: <strong>{old_north_count}</strong></li>
  <li>Renovated listings: <strong>{renovated_count}</strong></li>
</ul>
<p><a href="{sheet_url}">Open your Google Sheet to review</a></p>
<hr>
<p><em>Apartment Scanner Bot</em></p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = recipient
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, app_password)
            server.sendmail(gmail_user, recipient, msg.as_string())
        logger.info("Email sent to %s with %d new listings", recipient, n)
        return True
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        return False

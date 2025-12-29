#!/usr/bin/env python3
# ABOUTME: Notification system for CTR optimization
# ABOUTME: Sends alerts via Slack webhook and/or email

import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List
import requests

from .config import (
    SLACK_WEBHOOK_URL,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    NOTIFICATION_EMAIL
)


def send_slack_message(message: str, blocks: Optional[List] = None) -> bool:
    """Send message to Slack via webhook"""
    if not SLACK_WEBHOOK_URL:
        print("  Slack webhook not configured, skipping...")
        return False

    payload = {"text": message}
    if blocks:
        payload["blocks"] = blocks

    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        return response.status_code == 200
    except Exception as e:
        print(f"  Slack error: {e}")
        return False


def send_email(subject: str, body: str, html: bool = False) -> bool:
    """Send email notification"""
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, NOTIFICATION_EMAIL]):
        print("  Email not configured, skipping...")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = NOTIFICATION_EMAIL

        if html:
            msg.attach(MIMEText(body, 'html'))
        else:
            msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        return True
    except Exception as e:
        print(f"  Email error: {e}")
        return False


def notify_monthly_review_complete(
    experiments_started: int,
    experiments_completed: int,
    success_rate: float,
    report_path: str
) -> None:
    """Send notification that monthly review is complete"""

    message = f"""🎯 *CTR Monthly Review Complete*

*New Experiments:* {experiments_started}
*Completed Experiments:* {experiments_completed}
*Success Rate:* {success_rate:.1f}%

Report saved to: `{report_path}`"""

    send_slack_message(message)

    subject = f"CTR Monthly Review Complete - {experiments_started} new experiments"
    send_email(subject, message)


def notify_weekly_status(
    active_experiments: int,
    alerts: List[dict]
) -> None:
    """Send weekly status notification"""

    if alerts:
        alert_text = "\n".join([f"• {a['message']}" for a in alerts])
        message = f"""📊 *CTR Weekly Status*

*Active Experiments:* {active_experiments}

*Alerts:*
{alert_text}"""
    else:
        message = f"""📊 *CTR Weekly Status*

*Active Experiments:* {active_experiments}
No alerts this week."""

    send_slack_message(message)


def notify_alert(alert: dict) -> None:
    """Send immediate alert for significant changes"""

    if alert['type'] == 'decline':
        emoji = "🚨"
        urgency = "HIGH"
    else:
        emoji = "🎉"
        urgency = "INFO"

    message = f"""{emoji} *CTR Alert ({urgency})*

{alert['message']}

Page: `{alert['experiment'].get('page_slug', '')}`
Change: {alert['change_pct']:+.1f}%"""

    send_slack_message(message)

    if alert['type'] == 'decline':
        subject = f"⚠️ CTR Decline Alert: {alert['experiment'].get('page_slug', '')}"
        send_email(subject, message)


def notify_experiment_complete(
    page_slug: str,
    outcome: str,
    ctr_change: float,
    learnings: str
) -> None:
    """Notify when an experiment is completed"""

    emoji_map = {
        'improved': '✅',
        'worsened': '❌',
        'no_change': '➖',
        'inconclusive': '❓'
    }

    emoji = emoji_map.get(outcome, '❓')

    message = f"""{emoji} *Experiment Complete*

*Page:* `{page_slug}`
*Outcome:* {outcome}
*CTR Change:* {ctr_change:+.1f}%

*Learning:* {learnings}"""

    send_slack_message(message)


def send_monthly_report_email(
    experiments_started: List[dict],
    completed_experiments: List[dict],
    success_rate: float,
    report_path: str
) -> bool:
    """Send detailed monthly report email with all CTR changes and title updates"""
    from datetime import datetime
    from . import database as db

    month_name = datetime.now().strftime('%B %Y')

    # Build HTML email
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        .summary {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }}
        .summary-stat {{ display: inline-block; margin-right: 30px; }}
        .summary-stat .number {{ font-size: 24px; font-weight: bold; color: #3498db; }}
        .summary-stat .label {{ font-size: 12px; color: #7f8c8d; text-transform: uppercase; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th {{ background: #3498db; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px; border-bottom: 1px solid #ecf0f1; }}
        tr:hover {{ background: #f8f9fa; }}
        .improved {{ color: #27ae60; font-weight: bold; }}
        .worsened {{ color: #e74c3c; font-weight: bold; }}
        .no-change {{ color: #95a5a6; }}
        .old-title {{ color: #95a5a6; text-decoration: line-through; font-size: 13px; }}
        .new-title {{ color: #2c3e50; font-weight: 500; }}
        .ctr-change {{ font-weight: bold; }}
        .ctr-history {{ font-size: 12px; color: #7f8c8d; margin-top: 4px; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ecf0f1; color: #7f8c8d; font-size: 12px; }}
    </style>
</head>
<body>
    <h1>🎯 CTR Monthly Report - {month_name}</h1>

    <div class="summary">
        <div class="summary-stat">
            <div class="number">{len(experiments_started)}</div>
            <div class="label">New Experiments</div>
        </div>
        <div class="summary-stat">
            <div class="number">{len(completed_experiments)}</div>
            <div class="label">Completed</div>
        </div>
        <div class="summary-stat">
            <div class="number">{success_rate:.0f}%</div>
            <div class="label">Success Rate</div>
        </div>
    </div>
"""

    # Completed experiments section
    if completed_experiments:
        improved = [e for e in completed_experiments if e.get('outcome') == 'improved']
        worsened = [e for e in completed_experiments if e.get('outcome') == 'worsened']
        no_change = [e for e in completed_experiments if e.get('outcome') == 'no_change']

        html += """
    <h2>📊 Completed Experiments</h2>
    <table>
        <tr>
            <th>Page</th>
            <th>Old Title → New Title</th>
            <th>CTR Change</th>
            <th>Result</th>
        </tr>
"""
        for exp in completed_experiments:
            outcome = exp.get('outcome', 'unknown')
            ctr_change = exp.get('ctr_change_pct', 0)
            outcome_class = outcome.replace('_', '-')

            if ctr_change > 0:
                change_class = 'improved'
            elif ctr_change < 0:
                change_class = 'worsened'
            else:
                change_class = 'no-change'

            # Get CTR history for this page
            page_url = exp.get('page_url', '')
            ctr_progression = db.format_ctr_progression(page_url, months=3) if page_url else "N/A"

            html += f"""
        <tr>
            <td>
                <strong>{exp.get('page_slug', 'N/A')}</strong>
                <div class="ctr-history">📈 {ctr_progression}</div>
            </td>
            <td>
                <div class="old-title">{exp.get('old_title', 'N/A')}</div>
                <div class="new-title">{exp.get('new_title', 'N/A')}</div>
            </td>
            <td class="ctr-change {change_class}">{ctr_change:+.1f}%</td>
            <td class="{outcome_class}">{outcome.replace('_', ' ').title()}</td>
        </tr>
"""
        html += "</table>"

        # Summary of results
        html += f"""
    <p>
        <span class="improved">✅ {len(improved)} improved</span> &nbsp;|&nbsp;
        <span class="worsened">❌ {len(worsened)} worsened</span> &nbsp;|&nbsp;
        <span class="no-change">➖ {len(no_change)} no change</span>
    </p>
"""

    # New experiments section
    if experiments_started:
        html += """
    <h2>🚀 New Experiments Started</h2>
    <table>
        <tr>
            <th>Page</th>
            <th>Old Title → New Title</th>
            <th>Hypothesis</th>
        </tr>
"""
        for exp in experiments_started:
            html += f"""
        <tr>
            <td><strong>{exp.get('page_slug', 'N/A')}</strong></td>
            <td>
                <div class="old-title">{exp.get('old_title', 'N/A')}</div>
                <div class="new-title">{exp.get('new_title', 'N/A')}</div>
            </td>
            <td>{exp.get('hypothesis', 'N/A')[:100]}...</td>
        </tr>
"""
        html += "</table>"

    html += f"""
    <div class="footer">
        <p>Full report saved to: {report_path}</p>
        <p>Generated automatically by CTR Optimization System</p>
    </div>
</body>
</html>
"""

    subject = f"🎯 CTR Report {month_name}: {len(completed_experiments)} completed, {len(experiments_started)} new"
    return send_email(subject, html, html=True)

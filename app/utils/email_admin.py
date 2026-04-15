"""
Admin email notifications: account deactivation and reactivation.
Uses SMTP directly (sync, called from background tasks).
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

COLORS = {
    "cream": "#FAF8F4",
    "royal_blue": "#1A4480",
    "teal": "#2A8FA0",
    "text_dark": "#1C2B3A",
    "text_mid": "#4A5A6A",
    "sand_mid": "#DDD6C8"
}


def _base_template(content_html: str, username: str, title: str) -> str:
    return f"""
    <html>
        <head>
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
                body {{ margin: 0; padding: 0; background-color: {COLORS['cream']}; font-family: 'Inter', Helvetica, Arial, sans-serif; }}
                .container {{ max-width: 600px; margin: 40px auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid {COLORS['sand_mid']}; box-shadow: 0 4px 20px rgba(26,68,128,0.05); }}
                .header {{ background-color: {COLORS['royal_blue']}; padding: 40px 20px; text-align: center; }}
                .header h1 {{ color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; }}
                .content {{ padding: 40px 32px; color: {COLORS['text_dark']}; line-height: 1.6; }}
                .footer {{ padding: 32px; font-size: 13px; color: {COLORS['text_mid']}; border-top: 1px solid {COLORS['sand_mid']}; background-color: {COLORS['cream']}; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header"><h1>{title}</h1></div>
                <div class="content">
                    <p style="font-size: 16px;">Hello <strong>{username}</strong>,</p>
                    {content_html}
                </div>
                <div class="footer">
                    <p>Best regards,<br><strong>Articulink Administration</strong></p>
                    <p style="margin-top: 20px; font-size: 11px; opacity: 0.7;">
                        To appeal any decision, contact us at
                        <a href="mailto:articulink00@gmail.com" style="color: {COLORS['teal']};">articulink00@gmail.com</a>.
                    </p>
                </div>
            </div>
        </body>
    </html>
    """


def _send(msg: MIMEMultipart) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
        logger.warning("SMTP not configured — skipping admin email")
        return
    with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


def send_deactivation_email(email: str, username: str, deactivation_type: str, reason: str, end_date: datetime = None):
    try:
        smtp_from = os.getenv("SMTP_FROM", os.getenv("SMTP_USER"))
        type_label = "temporarily" if deactivation_type == "temporary" else "permanently"
        duration_info = (
            f"<p style='color:{COLORS['teal']}; font-weight:600;'>This deactivation ends on: {end_date.strftime('%B %d, %Y')}</p>"
            if deactivation_type == "temporary" and end_date else ""
        )
        content_html = f"""
        <p>Your account has been <strong>{type_label}</strong> deactivated.</p>
        <div style="background:#FFF5F5; border-left:4px solid #F87171; padding:20px; border-radius:4px; margin:24px 0;">
            <p style="color:#991B1B; font-weight:600; margin:0 0 8px; font-size:14px; text-transform:uppercase;">Reason</p>
            <p style="color:{COLORS['text_dark']}; margin:0;">{reason or 'No specific reason provided.'}</p>
        </div>
        {duration_info}
        <p>If you wish to appeal this decision, please contact us using the information below.</p>
        """
        html = _base_template(content_html, username, "Account Deactivated")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Account Notice: Articulink Deactivation"
        msg["From"] = smtp_from
        msg["To"] = email
        msg.attach(MIMEText(html, "html"))
        _send(msg)
        logger.info(f"📧 Deactivation notice sent to {email}")
    except Exception as e:
        logger.error(f"❌ Failed to send deactivation email: {str(e)}")


def send_activation_email(email: str, username: str):
    try:
        smtp_from = os.getenv("SMTP_FROM", os.getenv("SMTP_USER"))
        content_html = f"""
        <p>Welcome back! Your Articulink account is now <strong>fully reactivated</strong>.</p>
        <div style="background:#F0FDF4; border-left:4px solid {COLORS['teal']}; padding:20px; border-radius:4px; margin:24px 0;">
            <p style="color:#166534; font-weight:600; margin:0 0 8px; font-size:14px; text-transform:uppercase;">Status: Active</p>
            <p style="color:{COLORS['text_dark']}; margin:0;">Your access to all features has been restored. You can log in and continue where you left off.</p>
        </div>
        """
        html = _base_template(content_html, username, "Account Reactivated")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Welcome Back! Your Articulink Account is Now Active"
        msg["From"] = smtp_from
        msg["To"] = email
        msg.attach(MIMEText(html, "html"))
        _send(msg)
        logger.info(f"📧 Activation notice sent to {email}")
    except Exception as e:
        logger.error(f"❌ Failed to send activation email: {str(e)}")

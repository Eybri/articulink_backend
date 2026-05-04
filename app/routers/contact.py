"""
Contact form endpoint — receives messages from the ads/landing site
and forwards them to the Articulink team inbox via SMTP.
"""
import os
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from app.utils.email_service import email_service, _base_template

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Contact"])

TEAM_EMAIL = os.getenv("SMTP_USER", "averymikasa@gmail.com")

BRAND = {
    "cream": "#FAF8F4",
    "teal": "#2A8FA0",
    "tealLight": "#3DAFC4",
    "textDark": "#1C2B3A",
    "textMid": "#4A5A6A",
    "sandMid": "#DDD6C8",
}


class ContactRequest(BaseModel):
    email: EmailStr
    subject: str
    message: str


def _contact_email_html(data: ContactRequest) -> str:
    """Build a branded HTML email body for the contact form submission."""
    content = f"""
    <div style="text-align:center; margin-bottom:24px;">
        <div style="display:inline-block; width:52px; height:52px; line-height:52px; background-color:{BRAND['cream']};
            border:1px solid {BRAND['sandMid']}; border-radius:14px; font-size:28px; text-align:center;">💬</div>
    </div>
    <h2 style="margin:0 0 6px; font-size:18px; font-weight:800; color:{BRAND['textDark']}; text-align:center;">New Contact Message</h2>
    <p style="margin:0 0 20px; font-size:13px; color:{BRAND['textMid']}; text-align:center; line-height:1.5;">
        Someone reached out through the Articulink website.
    </p>

    <div style="background-color:{BRAND['cream']}; border:1px solid {BRAND['sandMid']}; border-radius:12px; padding:20px; margin-bottom:20px;">
        <table style="width:100%; border-collapse:collapse;">
            <tr>
                <td style="padding:8px 0; font-size:12px; font-weight:700; color:{BRAND['teal']}; text-transform:uppercase; letter-spacing:1px; vertical-align:top; width:80px;">From</td>
                <td style="padding:8px 0; font-size:14px; color:{BRAND['textDark']};">
                    <a href="mailto:{data.email}" style="color:{BRAND['teal']}; text-decoration:none;">{data.email}</a>
                </td>
            </tr>
            <tr>
                <td style="padding:8px 0; font-size:12px; font-weight:700; color:{BRAND['teal']}; text-transform:uppercase; letter-spacing:1px; vertical-align:top; width:80px;">Subject</td>
                <td style="padding:8px 0; font-size:14px; color:{BRAND['textDark']}; font-weight:600;">{data.subject}</td>
            </tr>
        </table>
    </div>

    <div style="background-color:{BRAND['cream']}; border:1px solid {BRAND['sandMid']}; border-radius:12px; padding:20px;">
        <p style="margin:0 0 8px; font-size:12px; font-weight:700; color:{BRAND['teal']}; text-transform:uppercase; letter-spacing:1px;">Message</p>
        <p style="margin:0; font-size:14px; color:{BRAND['textDark']}; line-height:1.7; white-space:pre-wrap;">{data.message}</p>
    </div>

    <div style="height:1px; background-color:{BRAND['sandMid']}; margin:24px 0 16px; opacity:0.5;"></div>
    <p style="margin:0; font-size:12px; color:{BRAND['textMid']}; text-align:center;">
        Reply directly to this email to respond to the sender.
    </p>
    """
    return _base_template(content)


@router.post("/contact")
async def send_contact_message(data: ContactRequest):
    """Receive a contact form submission and forward it to the team email."""
    if not data.email.strip() or not data.subject.strip() or not data.message.strip():
        raise HTTPException(status_code=400, detail="All fields are required.")

    email_subject = f"[Articulink Contact] {data.subject}"
    html_body = _contact_email_html(data)

    success = await email_service.send_email(
        subject=email_subject,
        recipients=[TEAM_EMAIL],
        body=html_body,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to send message. Please try again later.")

    logger.info(f"📧 Contact form message from {data.email} — subject: {data.subject}")
    return {"message": "Your message has been sent successfully."}

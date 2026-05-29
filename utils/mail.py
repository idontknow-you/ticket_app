import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from models.settings import get_setting


def get_smtp_config():
    """Load SMTP settings from the database."""
    return {
        "host":     get_setting("smtp_host", ""),
        "port":     int(get_setting("smtp_port", "587") or 587),
        "username": get_setting("smtp_username", ""),
        "password": get_setting("smtp_password", ""),
        "from_email": get_setting("smtp_from_email", ""),
        "from_name":  get_setting("smtp_from_name", "Support System"),
        "use_tls":  get_setting("smtp_use_tls", "true").lower() == "true",
    }


def send_email(to_email, subject, html_body, text_body=None):
    """
    Send an email via SMTP using settings stored in the DB.
    Returns (success: bool, error: str|None)
    """
    cfg = get_smtp_config()

    if not cfg["host"] or not cfg["from_email"]:
        return False, "SMTP is not configured. Set it in Admin → Settings."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{cfg['from_name']} <{cfg['from_email']}>"
        msg["To"]      = to_email

        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        if cfg["use_tls"]:
            server = smtplib.SMTP(cfg["host"], cfg["port"])
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"])

        if cfg["username"] and cfg["password"]:
            server.login(cfg["username"], cfg["password"])

        server.sendmail(cfg["from_email"], to_email, msg.as_string())
        server.quit()
        return True, None

    except Exception as e:
        return False, str(e)


def send_password_reset_email(user, reset_url):
    """Send a password reset link to a user."""
    subject = "Reset your password"
    from_name = get_setting("smtp_from_name", "Support System")

    html_body = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; color: #111;">
      <h2 style="font-size: 20px; margin-bottom: 8px;">Reset your password</h2>
      <p style="color: #6b7280; font-size: 14px; margin-bottom: 24px;">
        Hi {user.name or user.username}, someone requested a password reset for your account.
        Click the button below to set a new password. This link expires in 24 hours.
      </p>
      <a href="{reset_url}"
         style="display: inline-block; background: #111; color: #fff; text-decoration: none;
                font-size: 14px; font-weight: 500; padding: 10px 24px; border-radius: 8px;">
        Reset Password
      </a>
      <p style="color: #9ca3af; font-size: 12px; margin-top: 24px;">
        If you didn't request this, you can safely ignore this email.
      </p>
    </div>
    """

    text_body = (
        f"Hi {user.name or user.username},\n\n"
        f"Reset your password here: {reset_url}\n\n"
        f"This link expires in 24 hours.\n\n"
        f"If you didn't request this, ignore this email."
    )

    return send_email(user.email, subject, html_body, text_body)
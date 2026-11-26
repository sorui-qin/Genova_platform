"""Password reset links and mail.

Operators without SMTP can hand out a link instead:
    docker compose exec backend-api python -m backend.password_reset user@example.com
"""
import logging
import smtplib
import ssl
import sys
from email.message import EmailMessage
from urllib.parse import urlencode

from sqlalchemy import select

from backend.config import settings
from backend.models import User
from backend.security import PASSWORD_RESET_MINUTES, create_password_reset_token


logger = logging.getLogger(__name__)


def mail_enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_from and settings.public_base_url)


def reset_link(user: User) -> str:
    query = urlencode({"type": "reset_password", "token": create_password_reset_token(user.id, user.password_hash)})
    return f"{settings.public_base_url}/pswd_transit?{query}"


def send_reset_mail(to: str, link: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Genova 密码重置"
    message["From"] = settings.smtp_from
    message["To"] = to
    message.set_content(
        f"请在 {PASSWORD_RESET_MINUTES} 分钟内打开以下链接重置 Genova 密码，链接只能使用一次：\n\n{link}\n\n"
        "如果不是您本人操作，请忽略此邮件，您的密码不会改变。"
    )
    try:
        # Port 465 is implicit TLS; any other port must offer STARTTLS before credentials are sent.
        tls = ssl.create_default_context()
        if settings.smtp_port == 465:
            client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=tls)
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with client as smtp:
            if settings.smtp_port != 465:
                smtp.starttls(context=tls)
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("Password reset mail to %s failed", to)


def main(email: str) -> int:
    from backend.db import SessionLocal

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None or user.is_guest or not user.is_active:
            print("No active registered account uses that email", file=sys.stderr)
            return 1
        link = reset_link(user)
    print(link if settings.public_base_url else f"<site address>{link}  (set PUBLIC_BASE_URL for a full link)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m backend.password_reset <email>")
    sys.exit(main(sys.argv[1]))

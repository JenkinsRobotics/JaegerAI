"""Jaeger-owned SMTP transport for the Gateway's owner-approved outbox."""
from email.headerregistry import Address
from email.message import EmailMessage
import os
import smtplib
import ssl


def mailbox(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 254 or any(char in value for char in "\r\n"):
        raise ValueError("Expected one mailbox address")
    try:
        address = Address(addr_spec=value)
    except (ValueError, IndexError) as exc:
        raise ValueError("Expected one mailbox address") from exc
    if not address.domain or not address.username:
        raise ValueError("Expected one mailbox address")
    return address.addr_spec


def configured_email_adapter():
    host = os.getenv("JAEGER_SMTP_HOST", "").strip()
    if not host:
        return None
    sender = mailbox(os.environ["JAEGER_SMTP_FROM"])
    port = int(os.getenv("JAEGER_SMTP_PORT", "465"))
    use_starttls = os.getenv("JAEGER_SMTP_TLS", "implicit") == "starttls"
    username = os.getenv("JAEGER_SMTP_USER")
    password = os.getenv("JAEGER_SMTP_PASSWORD")
    if bool(username) != bool(password):
        raise ValueError("SMTP username and password must be configured together")

    def deliver(recipient, body):
        message = EmailMessage()
        message["From"] = sender
        message["To"] = mailbox(recipient)
        message["Subject"] = "Jaeger notification"
        message.set_content(body)
        context = ssl.create_default_context()
        client = (smtplib.SMTP(host, port, timeout=12) if use_starttls
                  else smtplib.SMTP_SSL(host, port, timeout=12, context=context))
        with client:
            if use_starttls:
                client.starttls(context=context)
            if username:
                client.login(username, password)
            client.send_message(message)
        return {"transport": "smtp", "accepted": True, "ok": True}

    return deliver

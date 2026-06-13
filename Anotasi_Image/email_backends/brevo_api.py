"""
Kirim email via Brevo REST API (HTTPS port 443).

Railway dan banyak PaaS memblokir SMTP (port 587/465), sehingga koneksi
smtp-relay.brevo.com sering timeout. API Brevo tidak kena blokir itu.
"""
import logging
import re

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


def _parse_from_email(from_email):
    """Dukung format: 'Nama <email@domain.com>' atau 'email@domain.com'."""
    if not from_email:
        from_email = settings.DEFAULT_FROM_EMAIL
    match = re.match(r"^(.+?)\s*<([^>]+)>$", from_email.strip())
    if match:
        return {"name": match.group(1).strip().strip('"'), "email": match.group(2).strip()}
    return {"name": "Anotasi Image", "email": from_email.strip()}


class BrevoAPIEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.api_key = getattr(settings, "BREVO_API_KEY", "") or ""
        self.timeout = getattr(settings, "BREVO_API_TIMEOUT", 30)

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        if not self.api_key:
            if not self.fail_silently:
                raise ValueError("BREVO_API_KEY belum diset di environment.")
            return 0

        sent = 0
        for message in email_messages:
            try:
                self._send_one(message)
                sent += 1
            except Exception:
                logger.exception("Brevo API gagal kirim ke %s", message.to)
                if not self.fail_silently:
                    raise
        return sent

    def _send_one(self, message):
        html_content = None
        text_content = message.body or ""

        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                html_content = content
                break

        payload = {
            "sender": _parse_from_email(message.from_email),
            "to": [{"email": addr} for addr in message.to],
            "subject": message.subject,
            "textContent": text_content,
        }
        if html_content:
            payload["htmlContent"] = html_content

        reply_to = getattr(message, "reply_to", None)
        if reply_to:
            payload["replyTo"] = {"email": reply_to[0]}

        response = requests.post(
            BREVO_SEND_URL,
            headers={
                "accept": "application/json",
                "api-key": self.api_key,
                "content-type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )

        if response.status_code >= 400:
            detail = response.text[:500]
            raise requests.HTTPError(
                f"Brevo API {response.status_code}: {detail}",
                response=response,
            )

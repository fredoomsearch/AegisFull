from __future__ import annotations

"""
Simple email service for AEGIS.

Responsibilities:
  - Load SMTP configuration from environment variables.
  - Provide a small, reusable EmailService class.
  - Support plain-text and HTML emails.
  - Optional template rendering from the `templates/` directory.
"""

import logging
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    _JINJA_AVAILABLE = True
except Exception:  # noqa: BLE001
    Environment = None  # type: ignore[assignment]
    FileSystemLoader = None  # type: ignore[assignment]
    select_autoescape = None  # type: ignore[assignment]
    _JINJA_AVAILABLE = False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


class EmailService:
    """
    Lightweight SMTP email service.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: Optional[bool] = None,
        use_ssl: Optional[bool] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        templates_dir: Optional[str | Path] = None,
    ) -> None:
        self.host: str = (host or os.getenv("SMTP_HOST") or "localhost").strip()
        self.port: int = int(port or os.getenv("SMTP_PORT") or "587")
        self.user: Optional[str] = (user or os.getenv("SMTP_USER") or "").strip() or None
        self.password: Optional[str] = (
            password or os.getenv("SMTP_PASSWORD") or ""
        ).strip() or None
        self.use_tls: bool = _env_bool("SMTP_USE_TLS", True) if use_tls is None else bool(use_tls)
        self.use_ssl: bool = _env_bool("SMTP_USE_SSL", False) if use_ssl is None else bool(use_ssl)

        self.from_email: str = (from_email or os.getenv("EMAIL_FROM") or "no-reply@example.com").strip()
        self.from_name: str = (from_name or os.getenv("EMAIL_FROM_NAME") or "AEGIS").strip()

        if templates_dir is None:
            base_dir = Path(__file__).resolve().parents[1]
            templates_dir = base_dir / "templates"
        self.templates_dir = Path(templates_dir)

        if _JINJA_AVAILABLE and self.templates_dir.exists():
            self._jinja_env = Environment(
                loader=FileSystemLoader(str(self.templates_dir)),
                autoescape=select_autoescape(["html", "xml"]),
            )
        else:
            self._jinja_env = None

        logger.info(
            "EmailService configured host=%s port=%s tls=%s ssl=%s from=%s",
            self.host,
            self.port,
            self.use_tls,
            self.use_ssl,
            self.from_email,
        )

    # -----------------------------------------------------
    # Public API
    # -----------------------------------------------------

    def send_email(
        self,
        to: str | Iterable[str],
        subject: str,
        *,
        html_body: Optional[str] = None,
        text_body: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Send an email.
        """
        recipients = [to] if isinstance(to, str) else list(to or [])
        if not recipients:
            logger.warning("EmailService.send_email called with no recipients.")
            return False

        if not html_body and not text_body:
            logger.warning("EmailService.send_email called with empty body.")
            return False

        msg = EmailMessage()
        msg["From"] = f"{self.from_name} <{self.from_email}>"
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject

        if headers:
            for k, v in headers.items():
                msg[k] = v

        if html_body and not text_body:
            text_body = "Please view this email in an HTML-compatible email client."

        if text_body:
            msg.set_content(text_body)

        if html_body:
            msg.add_alternative(html_body, subtype="html")

        try:
            self._send_via_smtp(msg, recipients)
            logger.info("Email sent to %s", recipients)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to send email to %s: %s", recipients, exc)
            return False

    def render_template(
        self,
        template_name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Render an HTML template from the templates directory.
        """
        context = context or {}

        if self._jinja_env is not None:
            try:
                tmpl = self._jinja_env.get_template(template_name)
                return tmpl.render(**context)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "EmailService.render_template Jinja2 failed for %s: %s",
                    template_name,
                    exc,
                )

        path = self.templates_dir / template_name
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "EmailService.render_template raw read failed for %s: %s",
                    template_name,
                    exc,
                )

        logger.warning("EmailService.render_template: template %s not found.", template_name)
        return ""

    # -----------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------

    def _send_via_smtp(self, msg: EmailMessage, recipients: Iterable[str]) -> None:
        """
        Low-level SMTP sending.
        """
        smtp_cls = smtplib.SMTP_SSL if self.use_ssl else smtplib.SMTP

        with smtp_cls(self.host, self.port, timeout=30) as server:
            server.ehlo()
            if self.use_tls and not self.use_ssl:
                try:
                    server.starttls()
                    server.ehlo()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("EmailService: STARTTLS failed: %s", exc)

            if self.user and self.password:
                try:
                    server.login(self.user, self.password)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("EmailService: login failed for %s: %s", self.user, exc)

            server.send_message(msg, from_addr=self.from_email, to_addrs=list(recipients))


email_service = EmailService()


def send_email(
    to: str | Iterable[str],
    subject: str,
    *,
    html_body: Optional[str] = None,
    text_body: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> bool:
    """
    Convenience wrapper around email_service.send_email.
    """
    return email_service.send_email(
        to=to,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        headers=headers,
    )

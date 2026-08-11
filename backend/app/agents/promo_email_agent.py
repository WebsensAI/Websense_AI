"""
app/agents/promo_email_agent.py
Runs automatically after a user analyzes a site and gets their report.
Generates a short AI-written follow-up email referencing their actual
results (via Groq) and sends it via SMTP.

This module never raises. Every public function returns a status dict
(see EmailStatus below) instead of throwing, so a broken SMTP config or
a flaky network can never take down the request that triggered it --
`send_promo_email` is always called from a background thread and its
return value is informational only.
"""
import json
import logging
import smtplib
import socket
import ssl
import threading
import time
from email.mime.text import MIMEText
from email.utils import formataddr

from groq import Groq

from app.config import Config

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
logger = logging.getLogger(__name__)
if not logger.handlers:
    # Make sure this module logs something useful even if the app hasn't
    # configured root logging -- keeps behavior close to the original
    # print()-based version, just with levels/timestamps.
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [PromoEmailAgent] %(levelname)s: %(message)s"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

MODEL = "llama-3.3-70b-versatile"

SMTP_TIMEOUT = 60             # seconds -- generous; slow SMTP providers under load can take a while
MAX_SEND_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 1      # exponential backoff: 1s, 2s, 4s between attempts

_client = Groq(api_key=Config.GROQ_API_KEY) if Config.GROQ_API_KEY else None


# ---------------------------------------------------------------------
# Status codes
# ---------------------------------------------------------------------
class EmailStatus:
    """String status codes returned by send_email() / send_promo_email()
    instead of a plain True/False, so callers (or logs) can tell exactly
    what happened and why."""
    SUCCESS = "success"
    SKIPPED_NO_RECIPIENT = "skipped_no_recipient"
    INVALID_CONFIG = "invalid_config"
    AUTH_FAILED = "auth_failed"
    TIMEOUT = "timeout"
    TLS_FAILED = "tls_failed"
    CONNECTION_FAILED = "connection_failed"
    SEND_FAILED = "send_failed"
    UNKNOWN_ERROR = "unknown_error"


def _result(status, message, attempts=0):
    return {"status": status, "message": message, "attempts": attempts}


# ---------------------------------------------------------------------
# AI email generation (unchanged behavior, logging only)
# ---------------------------------------------------------------------
def generate_promo_email(name, domain, report_data):
    top_recs = [r.get("t", "") for r in (report_data.get("recs") or [])[:3]]

    if not _client:
        return _fallback_email(name, domain, report_data, top_recs)

    system = (
        "You write short, friendly, non-spammy marketing emails for an "
        "AI website auditing tool. The email should reference the "
        "specific site and findings given, feel personal (not generic), "
        "and end with a clear but low-pressure call to action to come "
        "back and re-run the audit or explore the recommendations in "
        "the dashboard. Keep it under 150 words. Output valid JSON only."
    )
    user_prompt = f"""
User's name: {name or "there"}
Site just analyzed: {domain}
Overall score: {report_data.get("score")}/100 ({report_data.get("label")})
Top issues found: {json.dumps(top_recs)}

Return ONLY a JSON object:
{{"subject": "...", "body": "..."}}
No markdown, no commentary outside the JSON.
"""
    try:
        resp = _client.chat.completions.create(
            model=MODEL,
            max_tokens=500,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        if "subject" in parsed and "body" in parsed:
            return parsed
    except Exception as e:
        logger.warning("AI email generation failed, using fallback: %s", e)

    return _fallback_email(name, domain, report_data, top_recs)


def _fallback_email(name, domain, report_data, top_recs):
    greeting = f"Hi {name}," if name else "Hi there,"
    issues_line = "; ".join(top_recs) if top_recs else "a few opportunities to improve"
    return {
        "subject": f"Your {domain} audit is ready — score: {report_data.get('score')}/100",
        "body": (
            f"{greeting}\n\n"
            f"We just finished analyzing {domain}. It scored "
            f"{report_data.get('score')}/100 ({report_data.get('label')}).\n\n"
            f"Top things worth a look: {issues_line}.\n\n"
            f"Head back to the dashboard any time to see the full breakdown "
            f"and re-run the audit after you make changes.\n\n"
            f"— The AI Website Tester team"
        ),
    }


# ---------------------------------------------------------------------
# SMTP config validation
# ---------------------------------------------------------------------
def _validate_config():
    """Checks the SMTP configuration is present and well-formed *before*
    ever opening a socket, so a missing/broken .env fails fast with a
    clear reason instead of a confusing network-level error."""
    missing = [name for name, val in (
        ("SMTP_HOST", Config.SMTP_HOST),
        ("SMTP_PORT", Config.SMTP_PORT),
        ("SMTP_EMAIL", Config.SMTP_EMAIL),
        ("SMTP_PASSWORD", Config.SMTP_PASSWORD),
    ) if not val]
    if missing:
        return False, f"Missing SMTP configuration: {', '.join(missing)}. Set these in your .env file."

    if "@" not in str(Config.SMTP_EMAIL):
        return False, f"SMTP_EMAIL does not look like a valid email address: {Config.SMTP_EMAIL!r}"

    try:
        port = int(Config.SMTP_PORT)
    except (TypeError, ValueError):
        return False, f"SMTP_PORT is not a valid integer: {Config.SMTP_PORT!r}"
    if not (0 < port < 65536):
        return False, f"SMTP_PORT is out of range: {port}"

    return True, None


# ---------------------------------------------------------------------
# Connection management (reuse a single SMTP connection when possible)
# ---------------------------------------------------------------------
# smtplib.SMTP objects aren't safe for concurrent use from multiple
# threads, and promo emails are fired from a background thread per
# request, so a single lock serializes access to the shared connection.
_smtp_lock = threading.Lock()
_smtp_conn = None


def _open_new_connection():
    """Connect -> EHLO -> STARTTLS -> EHLO -> LOGIN. Raises on failure;
    callers classify and handle the exception."""
    logger.info("Opening new SMTP connection to %s:%s ...", Config.SMTP_HOST, Config.SMTP_PORT)
    server = smtplib.SMTP(Config.SMTP_HOST, int(Config.SMTP_PORT), timeout=SMTP_TIMEOUT)

    # EHLO before STARTTLS so the server advertises its capabilities
    # (including whether it supports STARTTLS at all) over the plain
    # connection first.
    code, resp = server.ehlo()
    logger.debug("EHLO (pre-TLS) -> %s %s", code, resp)

    if not server.has_extn("starttls"):
        raise smtplib.SMTPNotSupportedError("SMTP server does not advertise STARTTLS support.")

    context = ssl.create_default_context()
    code, resp = server.starttls(context=context)
    logger.debug("STARTTLS -> %s %s", code, resp)

    # RFC 3207: the client MUST discard any knowledge from the pre-TLS
    # EHLO and re-issue EHLO once the TLS session is established, since
    # the earlier plaintext response can't be trusted.
    code, resp = server.ehlo()
    logger.debug("EHLO (post-TLS) -> %s %s", code, resp)

    server.login(Config.SMTP_EMAIL, Config.SMTP_PASSWORD)
    logger.info("SMTP login succeeded for %s.", Config.SMTP_EMAIL)
    return server


def _close_cached_connection():
    """Closes and clears the cached connection. Caller must hold `_smtp_lock`."""
    global _smtp_conn
    if _smtp_conn is not None:
        try:
            _smtp_conn.quit()
        except Exception:
            try:
                _smtp_conn.close()
            except Exception:
                pass
        _smtp_conn = None


def _get_connection(force_new=False):
    """Returns a live, authenticated SMTP connection -- reusing the
    cached one (verified with NOOP) when possible, otherwise opening a
    fresh one. Caller must hold `_smtp_lock`."""
    global _smtp_conn

    if force_new:
        _close_cached_connection()

    if _smtp_conn is not None:
        try:
            status, _ = _smtp_conn.noop()
            if status == 250:
                logger.debug("Reusing existing SMTP connection.")
                return _smtp_conn
            logger.info("Cached SMTP connection returned status %s on NOOP; reconnecting.", status)
        except Exception as e:
            logger.info("Cached SMTP connection is no longer usable (%s); reconnecting.", e)
        _close_cached_connection()

    _smtp_conn = _open_new_connection()
    return _smtp_conn


# ---------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------
def _looks_like_timeout(e):
    """smtplib's getreply() catches a read timeout (a plain OSError /
    TimeoutError) and re-raises it as SMTPServerDisconnected with the
    message 'Connection unexpectedly closed: <original error>' -- it
    does NOT keep it as a distinct exception type. So a genuine timeout
    surfaces looking like a generic disconnect unless we specifically
    unwrap it, either via the implicit exception chain (__context__/
    __cause__) or, failing that, by matching the message text."""
    seen = e
    for _ in range(5):
        if isinstance(seen, (socket.timeout, TimeoutError)):
            return True
        seen = getattr(seen, "__cause__", None) or getattr(seen, "__context__", None)
        if seen is None:
            break
    return "timed out" in str(e).lower() or "timeout" in str(e).lower()


def _classify_error(e):
    """Maps an exception raised during connect/STARTTLS/login/send to
    one of the EmailStatus codes, with a human-readable message."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return (EmailStatus.AUTH_FAILED,
                f"SMTP authentication failed ({e.smtp_code}): {e.smtp_error}. "
                f"Check SMTP_EMAIL/SMTP_PASSWORD -- for Gmail this must be an App Password, not your normal password.")

    if isinstance(e, (socket.timeout, TimeoutError)) or (
            isinstance(e, smtplib.SMTPServerDisconnected) and _looks_like_timeout(e)):
        return (EmailStatus.TIMEOUT,
                f"Connection to {Config.SMTP_HOST}:{Config.SMTP_PORT} timed out after {SMTP_TIMEOUT}s: {e}")

    if isinstance(e, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return (EmailStatus.TLS_FAILED, f"TLS/STARTTLS negotiation failed: {e}")

    if isinstance(e, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, ConnectionError, OSError)):
        return (EmailStatus.CONNECTION_FAILED,
                f"Could not connect to or stay connected to {Config.SMTP_HOST}:{Config.SMTP_PORT}: {e}")

    if isinstance(e, smtplib.SMTPException):
        return EmailStatus.SEND_FAILED, f"SMTP error while sending: {e}"

    return EmailStatus.UNKNOWN_ERROR, f"Unexpected error while sending email: {e}"


def _is_retryable(status, exc):
    """Decides whether a given failure is worth retrying.

    - TIMEOUT / CONNECTION_FAILED / UNKNOWN_ERROR: transient, retry.
    - SEND_FAILED: only retry if the server gave a 4xx (transient)
      response; a 5xx is a permanent rejection and retrying wastes time.
    - AUTH_FAILED / TLS_FAILED / INVALID_CONFIG: permanent misconfiguration
      -- retrying won't fix a wrong password or an unsupported server,
      and hammering a login endpoint risks the provider locking the
      account, so these fail fast instead.
    """
    if status in (EmailStatus.TIMEOUT, EmailStatus.CONNECTION_FAILED, EmailStatus.UNKNOWN_ERROR):
        return True
    if status == EmailStatus.SEND_FAILED:
        code = getattr(exc, "smtp_code", None)
        return code is not None and 400 <= code < 500
    return False


# ---------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------
def send_email(to_email, subject, body):
    """
    Sends an email via SMTP with up to MAX_SEND_ATTEMPTS tries and
    exponential backoff between retryable failures, reusing the cached
    SMTP connection when possible.

    Never raises. Always returns a status dict:
        {"status": <EmailStatus.*>, "message": str, "attempts": int}
    """
    try:
        ok, reason = _validate_config()
        if not ok:
            logger.warning("SMTP configuration invalid, skipping send: %s", reason)
            return _result(EmailStatus.INVALID_CONFIG, reason, attempts=0)

        if not to_email:
            logger.warning("No recipient email address given, skipping send.")
            return _result(EmailStatus.SKIPPED_NO_RECIPIENT, "No recipient email address provided.", attempts=0)

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = formataddr(("WebSense AI", Config.SMTP_EMAIL))
        msg["To"] = to_email

        last_status, last_message = EmailStatus.UNKNOWN_ERROR, "Unknown error."
        attempt = 0
        force_new = False

        with _smtp_lock:
            while attempt < MAX_SEND_ATTEMPTS:
                attempt += 1
                try:
                    logger.info("Sending email to %s (attempt %d/%d)...", to_email, attempt, MAX_SEND_ATTEMPTS)
                    server = _get_connection(force_new=force_new)
                    server.sendmail(Config.SMTP_EMAIL, [to_email], msg.as_string())
                    logger.info("Email sent to %s on attempt %d/%d.", to_email, attempt, MAX_SEND_ATTEMPTS)
                    return _result(EmailStatus.SUCCESS, "Email sent successfully.", attempts=attempt)

                except Exception as e:
                    status, message = _classify_error(e)
                    last_status, last_message = status, message
                    logger.error("Attempt %d/%d failed [%s]: %s", attempt, MAX_SEND_ATTEMPTS, status, message)

                    # The connection is presumably unusable after any
                    # failure -- force a fresh one if we retry.
                    force_new = True

                    if not _is_retryable(status, e):
                        logger.error("Failure type '%s' is not retryable; giving up.", status)
                        _close_cached_connection()
                        return _result(status, message, attempts=attempt)

                    if attempt < MAX_SEND_ATTEMPTS:
                        backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                        logger.info("Retryable failure -- waiting %ds before attempt %d/%d.",
                                    backoff, attempt + 1, MAX_SEND_ATTEMPTS)
                        time.sleep(backoff)

            logger.error("Giving up after %d attempts sending to %s: %s", attempt, to_email, last_message)
            _close_cached_connection()
            return _result(last_status, last_message, attempts=attempt)

    except Exception as e:
        # Belt-and-braces: no matter what goes wrong above (including
        # bugs in this function itself), never let it escape and crash
        # the calling thread/request.
        logger.exception("Unexpected error in send_email: %s", e)
        return _result(EmailStatus.UNKNOWN_ERROR, f"Unexpected error: {e}", attempts=0)


def send_promo_email(to_email, name, domain, report_data):
    """
    Entry point run in a background thread right after an analysis
    completes. Never raises -- always returns a status dict (see
    send_email above); the caller treats this as fire-and-forget.
    """
    try:
        if not to_email:
            logger.info("No user email on session; skipping promo email.")
            return _result(EmailStatus.SKIPPED_NO_RECIPIENT, "No recipient email address provided.", attempts=0)

        email_content = generate_promo_email(name, domain, report_data)
        result = send_email(to_email, email_content["subject"], email_content["body"])
        logger.info("Promo email to %s finished: status=%s attempts=%s",
                    to_email, result["status"], result["attempts"])
        return result

    except Exception as e:
        logger.exception("Unexpected error in send_promo_email: %s", e)
        return _result(EmailStatus.UNKNOWN_ERROR, f"Unexpected error: {e}", attempts=0)

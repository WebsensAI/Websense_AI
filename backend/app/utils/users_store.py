"""
app/utils/users_store.py
MySQL-backed user store (via SQLAlchemy). This replaces the original
JSON-file "database" -- the public API is unchanged on purpose so no
other file (routes.py, etc.) needs to change:

    get_user(email)          -> dict | None
    authenticate(email, pw)  -> (user_dict, error_message)

Auth model: since there's no separate signup page yet, the first time
someone logs in with a given email, an account is created for them
with whatever password they typed (auto-register on first login).
Every login after that must match the original password hash.
"""
import logging

from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.models.user import User
from app.utils.db import DatabaseUnavailableError, session_scope

logger = logging.getLogger(__name__)


def _normalize_email(email):
    return (email or "").strip().lower()


def _display_name(email):
    """No name field on the login form, so derive a friendly display
    name from the part of the email before the @."""
    return email.split("@")[0].replace(".", " ").replace("_", " ").title()


def get_user(email):
    """Returns a plain dict for the user, or None if no such account
    exists. Returns None (rather than raising) if the database can't
    be reached, since callers historically only expect a dict or None."""
    email = _normalize_email(email)
    if not email:
        return None

    try:
        with session_scope() as session:
            user = session.query(User).filter(User.email == email).one_or_none()
            return user.to_dict() if user else None
    except DatabaseUnavailableError as e:
        logger.error("get_user(%s) failed: %s", email, e)
        return None


def authenticate(email, password):
    """
    Returns (user_dict, error_message).
    On success: (user, None).
    On failure: (None, "reason").
    Creates the account automatically on first-ever login for that email.
    """
    email = _normalize_email(email)
    if not email:
        return None, "Email is required."
    if not password:
        return None, "Password is required."

    try:
        with session_scope() as session:
            existing = session.query(User).filter(User.email == email).one_or_none()

            if existing is not None:
                if not check_password_hash(existing.password_hash, password):
                    return None, "Incorrect password."
                return existing.to_dict(), None

            # First time we've seen this email -- auto-register it.
            new_user = User(
                email=email,
                name=_display_name(email),
                password_hash=generate_password_hash(password),
            )
            session.add(new_user)
            try:
                session.flush()  # assigns the id and surfaces a duplicate-email
                                  # error now, before we commit, so we can react to it
            except IntegrityError:
                # Two concurrent first-logins for the same brand-new email --
                # someone else's request won the race and created it first.
                # Roll back this attempt and fall back to a normal login
                # against the row that now exists instead of erroring out.
                session.rollback()
                existing = session.query(User).filter(User.email == email).one_or_none()
                if existing is None:
                    logger.error("Duplicate email error for %s but no row found afterwards.", email)
                    return None, "We couldn't create your account. Please try again."
                if not check_password_hash(existing.password_hash, password):
                    return None, "Incorrect password."
                return existing.to_dict(), None

            return new_user.to_dict(), None

    except DatabaseUnavailableError as e:
        logger.error("authenticate(%s) failed: %s", email, e)
        return None, "We couldn't reach the database right now. Please try again in a moment."

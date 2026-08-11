"""
app/models/user.py
SQLAlchemy ORM model backing the `users` table in MySQL.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        """Plain dict snapshot -- safe to use after the DB session that
        loaded this row has been closed (avoids DetachedInstanceError)."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "password_hash": self.password_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<User id={self.id} email={self.email!r}>"

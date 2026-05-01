from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import UserMixin, current_user
from werkzeug.security import check_password_hash, generate_password_hash


class AuthUser(UserMixin):
    def __init__(self, user_id: int, email: str, is_admin: bool, is_active: bool = True):
        self.id = str(user_id)
        self.email = email
        self.is_admin = is_admin
        self._is_active = is_active

    @property
    def is_active(self) -> bool:
        return bool(self._is_active)


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    return check_password_hash(password_hash, password)


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped

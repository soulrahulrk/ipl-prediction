from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipl_predictor.auth import hash_password
from ipl_predictor.config import get_settings
from ipl_predictor.db import get_db_session, init_db, init_engine
from ipl_predictor.models import AuditLog, User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap first admin user.")
    parser.add_argument("--email", default=os.getenv("ADMIN_EMAIL", ""), help="Admin email (or ADMIN_EMAIL env).")
    parser.add_argument("--password", default=os.getenv("ADMIN_PASSWORD", ""), help="Admin password (or ADMIN_PASSWORD env).")
    parser.add_argument(
        "--promote-existing",
        action="store_true",
        help="Promote existing user to admin if email exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    init_engine(settings.database_url)
    init_db()

    db_session = get_db_session()

    admin_count = db_session.query(User).filter(User.is_admin.is_(True), User.is_active.is_(True)).count()
    if admin_count > 0:
        print(f"Admin already exists (count={admin_count}). No action required.")
        return

    email = str(args.email).strip().lower()
    password = str(args.password)

    if not email:
        raise SystemExit("Provide --email or ADMIN_EMAIL to bootstrap first admin.")

    existing = db_session.query(User).filter(User.email == email).one_or_none()

    if existing is not None:
        if not args.promote_existing:
            raise SystemExit(
                "User exists but is not admin. Re-run with --promote-existing to promote safely."
            )
        existing.is_admin = True
        if password:
            existing.password_hash = hash_password(password)
        db_session.add(existing)
        db_session.add(
            AuditLog(
                user_id=existing.id,
                action="seed.promote_first_admin",
                metadata_json={"email": email},
            )
        )
        db_session.commit()
        print(f"Promoted existing user to admin: {email}")
        return

    if not password:
        raise SystemExit("Provide --password or ADMIN_PASSWORD when creating first admin.")

    user = User(email=email, password_hash=hash_password(password), is_admin=True, is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(
        AuditLog(
            user_id=user.id,
            action="seed.create_first_admin",
            metadata_json={"email": email},
        )
    )
    db_session.commit()

    print(f"Created first admin user: {email}")


if __name__ == "__main__":
    main()

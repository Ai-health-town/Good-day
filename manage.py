"""Private operator recovery: python manage.py reset-admin USERNAME.

Requires the same private DATABASE_URL as the deployed app. Never expose this
script as a public endpoint. Passwords are read using getpass, not arguments.
"""
import argparse
import getpass
import hashlib
import os
import tomllib
from pathlib import Path

from sqlalchemy import delete, select, update
from workspace import Store, WorkspaceError, attempts, clean_username, password_hash, sessions, users


def main():
    parser = argparse.ArgumentParser(description="Recover a G'day administrator account")
    parser.add_argument("action", choices=["reset-admin"])
    parser.add_argument("username")
    args = parser.parse_args()
    config_file = Path(__file__).parent / ".streamlit" / "secrets.toml"
    config = tomllib.loads(config_file.read_text()) if config_file.exists() else {}
    database_url = os.environ.get("DATABASE_URL") or config.get("DATABASE_URL")
    if not database_url:
        raise WorkspaceError("ضع DATABASE_URL في متغير البيئة أو ملف .streamlit/secrets.toml المحلي.")
    password = getpass.getpass("New administrator password (at least 12 characters): ")
    if password != getpass.getpass("Repeat new password: "):
        raise WorkspaceError("كلمتا المرور غير متطابقتين.")
    hashed, username = password_hash(password), clean_username(args.username)
    store = Store(database_url)
    with store.transaction() as conn:
        target = conn.execute(select(users).where(users.c.username == username, users.c.role == "admin")).mappings().first()
        if not target:
            raise WorkspaceError("حساب المدير غير موجود.")
        conn.execute(update(users).where(users.c.id == target["id"]).values(password_hash=hashed, active=True))
        conn.execute(delete(sessions).where(sessions.c.user_id == target["id"]))
        conn.execute(delete(attempts).where(attempts.c.username_hash == hashlib.sha256(username.encode()).hexdigest()))
        store._log(conn, {"name": "صيانة حساب المدير"}, "استعادة دخول المدير", username)
    print("Administrator password updated. Old sessions revoked.")


if __name__ == "__main__":
    try:
        main()
    except WorkspaceError as exc:
        raise SystemExit(str(exc))

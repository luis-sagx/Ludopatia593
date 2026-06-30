"""
Inicializa la base: crea tablas, siembra equipos/fixtures de demo y un admin.
La contraseña admin se toma de ADMIN_PASSWORD (entorno), nunca hardcodeada.

Uso: python -m app.seed
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

from .db.session import Base, engine, SessionLocal
from .db.models import User, Team, Fixture, FixtureStatus, Role
from .core.security import hash_password
from .ml.inference import inference

DEMO_FIXTURES = [
    ("group_a", "Argentina", "Mexico"),
    ("group_a", "France", "USA"),
    ("group_b", "Brazil", "Morocco"),
    ("group_b", "Spain", "Japan"),
    ("group_c", "England", "Senegal"),
    ("group_c", "Portugal", "Ecuador"),
]


def main():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        # admin (solo si no existe)
        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
        if not db.query(User).filter(User.email == admin_email).first():
            pw = os.getenv("ADMIN_PASSWORD")
            if not pw:
                raise SystemExit("define ADMIN_PASSWORD en el entorno para crear el admin")
            db.add(User(email=admin_email, password_hash=hash_password(pw), role=Role.admin))

        # equipos desde el modelo (si está cargado)
        inference.load()
        for name in inference.teams:
            if not db.query(Team).filter(Team.name == name).first():
                db.add(Team(name=name))

        # fixtures demo
        base = datetime.now(timezone.utc) + timedelta(days=1)
        for i, (stage, h, a) in enumerate(DEMO_FIXTURES):
            ext = f"demo-{i}"
            if not db.query(Fixture).filter(Fixture.external_id == ext).first():
                db.add(Fixture(
                    external_id=ext, stage=stage, home_team=h, away_team=a,
                    kickoff_utc=base + timedelta(hours=3 * i), neutral=True,
                    status=FixtureStatus.scheduled,
                ))
        db.commit()
        print(f"seed ok: {db.query(Team).count()} equipos, {db.query(Fixture).count()} fixtures")
    finally:
        db.close()


if __name__ == "__main__":
    main()

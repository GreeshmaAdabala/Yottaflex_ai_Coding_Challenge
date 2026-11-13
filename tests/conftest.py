import os
from datetime import date

import pytest

from database.db import db
from generator.generate_data import generate_dataset

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "false"


@pytest.fixture
def workforce_app():
    from app import create_app

    app = create_app(
        {
            "TESTING": True,
            "AUTO_SEED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "HORIZON_START": "2026-01-01",
        }
    )
    with app.app_context():
        db.drop_all()
        db.create_all()
        generate_dataset(
            employees=50,
            skills=30,
            projects=10,
            seed=20261022,
            horizon_start=date(2026, 1, 1),
            horizon_weeks=52,
        )
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(workforce_app):
    return workforce_app.test_client()

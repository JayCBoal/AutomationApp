"""
A database built by an earlier version of AutoApp must produce an explanation,
not a bare "Internal Server Error".
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import get_db
from app.main import app
from core.models import Base
from app.schema_check import schema_problems
from conftest import SERVER_DATABASE_URL

pytestmark = pytest.mark.skipif(
    bool(SERVER_DATABASE_URL),
    reason="these tests take columns out of the database, which the shared server test database must keep")


@pytest.fixture
def old_database(tmp_path):
    """A database as an earlier version would have built it: two columns and one table short."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE StepDefinitions DROP COLUMN DisplayOrder"))
        connection.execute(text("ALTER TABLE StepDefinitions DROP COLUMN AllowedValues"))
        connection.execute(text("DROP TABLE Operations"))
        connection.execute(text("INSERT INTO StepTypes (id, Name, Code) VALUES (1, 'Copy Files', 'COPY_FILES')"))
        connection.execute(text("INSERT INTO StepDefinitions (StepType_id, ParameterName) VALUES (1, 'Source')"))
    yield engine
    engine.dispose()


@pytest.fixture
def client_on(old_database):
    make_session = sessionmaker(bind=old_database)

    def override_get_db():
        session = make_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def test_an_up_to_date_database_has_no_problems(db):
    assert schema_problems(db.connection()) == []


def test_missing_tables_and_columns_are_named(old_database):
    with old_database.connect() as connection:
        problems = schema_problems(connection)

    assert problems == ["StepDefinitions.DisplayOrder", "StepDefinitions.AllowedValues", "table Operations"]


def test_a_route_that_needs_a_missing_column_explains_what_is_wrong(client_on):
    response = client_on.get("/api/v1/step-types")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail.startswith("The database is out of date for this version of AutoApp.")
    assert "StepDefinitions.DisplayOrder" in detail and "table Operations" in detail
    assert "README" in detail


def test_a_route_that_does_not_need_what_is_missing_still_works(client_on):
    assert client_on.get("/api/v1/jobs").status_code == 200


def test_the_server_says_so_in_its_log_when_it_starts(old_database, caplog):
    make_session = sessionmaker(bind=old_database)

    def override_get_db():
        session = make_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with caplog.at_level("ERROR", logger="AutoApp.API"), TestClient(app):
            pass
    finally:
        app.dependency_overrides.clear()

    assert any("The database is out of date" in record.getMessage() and "StepDefinitions.DisplayOrder" in record.getMessage()
               for record in caplog.records)

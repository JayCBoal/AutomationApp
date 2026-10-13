import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.catalog import sync_catalog
from app.database import get_db
from app.routers import jobs, operations, step_types, telemetry, variables

# The web interface: plain HTML, CSS and JavaScript files that call the API above
UI_DIR = Path(__file__).resolve().parents[1] / "ui"



@asynccontextmanager
async def lifespan(app: FastAPI):
    """On startup, bring the step catalog tables into line with the handlers in the code."""
    provide_db = app.dependency_overrides.get(get_db, get_db)
    sessions = provide_db()
    try:
        sync_catalog(next(sessions))
    except SQLAlchemyError as e:
        logging.getLogger("AutoApp.API").warning(
            "The step catalog was not updated (are the database tables created?): %s", e)
    finally:
        sessions.close()
    yield


app = FastAPI(
    title="AutoApp Core REST API",
    version="1.0.0",
    description="Execution Harness & Payload Abstraction Layer for WLA Engines",
    lifespan=lifespan,
)

# Register APIRouters
app.include_router(jobs.router)
app.include_router(telemetry.router)
app.include_router(operations.router)
app.include_router(step_types.router)
app.include_router(variables.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "HEALTHY", "service": "AutoApp Core API"}


@app.get("/", include_in_schema=False)
def open_web_interface():
    return RedirectResponse("/ui/")


app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")

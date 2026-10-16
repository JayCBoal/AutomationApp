import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.catalog import sync_catalog
from app.database import get_db
from app.routers import (
    definitions, endpoints, history, jobs, launches, lookups, operations, registry, settings, step_types, telemetry,
    variables
)
from app.schema_check import out_of_date_message, schema_problems

logger = logging.getLogger("AutoApp.API")


def database_shortfall() -> list:
    """What this version needs that the database lacks; empty if nothing, or if it cannot be told."""
    provide_db = app.dependency_overrides.get(get_db, get_db)
    sessions = provide_db()
    try:
        return schema_problems(next(sessions).connection())
    except SQLAlchemyError:
        return []
    finally:
        sessions.close()

# The web interface: plain HTML, CSS and JavaScript files that call the API above
UI_DIR = Path(__file__).resolve().parents[1] / "ui"



@asynccontextmanager
async def lifespan(app: FastAPI):
    """On startup, check the database fits this version, and bring the step catalog into line with the handlers."""
    shortfall = database_shortfall()
    if shortfall:
        logger.error(out_of_date_message(shortfall))
    provide_db = app.dependency_overrides.get(get_db, get_db)
    sessions = provide_db()
    try:
        sync_catalog(next(sessions))
    except SQLAlchemyError as e:
        logger.warning("The step catalog was not updated: %s", str(e).splitlines()[0])
    finally:
        sessions.close()
    yield


app = FastAPI(
    title="AutoApp Core REST API",
    version="1.0.0",
    description="Execution Harness & Payload Abstraction Layer for WLA Engines",
    lifespan=lifespan,
)

@app.exception_handler(SQLAlchemyError)
def database_error(request: Request, error: SQLAlchemyError):
    """A database failure, explained. Most often the database was built by an earlier version of AutoApp."""
    shortfall = database_shortfall()
    if shortfall:
        detail = out_of_date_message(shortfall)
    else:
        detail = "The database returned an error: " + str(error).splitlines()[0]
    logger.error("%s %s failed: %s", request.method, request.url.path, detail)
    return JSONResponse(status_code=500, content={"detail": detail})


# Register APIRouters
app.include_router(jobs.router)
app.include_router(telemetry.router)
app.include_router(operations.router)
app.include_router(step_types.router)
app.include_router(endpoints.router)
app.include_router(lookups.router)
app.include_router(history.router)
app.include_router(registry.applications)
app.include_router(registry.entities)
app.include_router(registry.sites)
app.include_router(registry.schedulers)
app.include_router(registry.tags)
app.include_router(registry.tag_variables)
for router in definitions.routers:
    app.include_router(router)
app.include_router(variables.router)
app.include_router(settings.router)
app.include_router(launches.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "HEALTHY", "service": "AutoApp Core API"}


@app.get("/", include_in_schema=False)
def open_web_interface():
    return RedirectResponse("/ui/")


app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")

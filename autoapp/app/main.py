import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.catalog import sync_catalog
from app.database import get_db
from app.log_agent import remove_old_logs
from app.routers import (
    conditions, definitions, endpoints, history, jobs, launches, lookups, operations, registry, reruns, schedulers, settings,
    step_types, telemetry, variables
)
from app.schema_check import out_of_date_message, schema_problems

logger = logging.getLogger("AutoApp.API")

LOG_CLEANUP_SECONDS = 24 * 60 * 60      # old job logs are looked for at startup, then once a day


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



def remove_old_logs_now() -> None:
    """Removes the job logs older than the Settings page allows. A failure is logged and tried again tomorrow."""
    sessions = app.dependency_overrides.get(get_db, get_db)()
    try:
        removed = remove_old_logs(next(sessions))
        if removed:
            logger.info("Removed %d job logs older than the Settings page allows.", removed)
    except (SQLAlchemyError, OSError) as e:
        logger.warning("Old job logs were not removed: %s", str(e).splitlines()[0])
    finally:
        sessions.close()


async def remove_old_logs_daily() -> None:
    while True:
        await asyncio.to_thread(remove_old_logs_now)
        await asyncio.sleep(LOG_CLEANUP_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup, check the database fits this version, and bring the step catalog into line with the handlers.
    While running, remove old job logs once a day.
    """
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
    cleanup = asyncio.create_task(remove_old_logs_daily())
    yield
    cleanup.cancel()


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
app.include_router(schedulers.router)
app.include_router(registry.tags)
app.include_router(registry.tag_variables)
for router in definitions.routers:
    app.include_router(router)
app.include_router(variables.router)
app.include_router(settings.router)
app.include_router(launches.router)
app.include_router(reruns.router)
app.include_router(conditions.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "HEALTHY", "service": "AutoApp Core API"}


@app.get("/", include_in_schema=False)
def open_web_interface():
    return RedirectResponse("/ui/")


class _PageFiles(StaticFiles):
    """The web interface's files, marked so a browser asks for a newer copy each time rather than using an old one."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/ui", _PageFiles(directory=UI_DIR, html=True), name="ui")

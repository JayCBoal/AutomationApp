from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routers import jobs, operations, telemetry, variables

# The web interface: plain HTML, CSS and JavaScript files that call the API above
UI_DIR = Path(__file__).resolve().parents[1] / "ui"

app = FastAPI(
    title="AutoApp Core REST API",
    version="1.0.0",
    description="Execution Harness & Payload Abstraction Layer for WLA Engines"
)

# Register APIRouters
app.include_router(jobs.router)
app.include_router(telemetry.router)
app.include_router(operations.router)
app.include_router(variables.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "HEALTHY", "service": "AutoApp Core API"}


@app.get("/", include_in_schema=False)
def open_web_interface():
    return RedirectResponse("/ui/")


app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")

from fastapi import FastAPI
from app.routers import jobs, telemetry, variables

app = FastAPI(
    title="AutoApp Core REST API",
    version="1.0.0",
    description="Execution Harness & Payload Abstraction Layer for WLA Engines"
)

# Register APIRouters
app.include_router(jobs.router)
app.include_router(telemetry.router)
app.include_router(variables.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "HEALTHY", "service": "AutoApp Core API"}
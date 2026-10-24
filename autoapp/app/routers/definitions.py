"""
Searching, viewing, changing and removing applications, entities, sites, endpoints and tags:

    GET    /api/v1/{kind}            search; any field can be a criterion (part of it, any case)
    GET    /api/v1/{kind}/{name}     one, with its variables and what uses it
    PUT    /api/v1/{kind}/{name}     change it; fields left out stay as they are
    DELETE /api/v1/{kind}/{name}     remove it, if nothing uses it

where kind is applications, entities, sites, endpoints or tags. A tag's name is
its path, e.g. /api/v1/tags/Finance/Reporting. Registering a new one is
POST /api/v1/{kind}. See app/registry_store.py.
"""
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from core.database import get_db
from app.job_store import JobStoreError
from app import registry_store as store

EDITOR_NAME = "web interface"


def make_router(kind_key: str) -> APIRouter:
    kind = store.KINDS[kind_key]
    router = APIRouter(prefix=f"/api/v1/{kind_key}", tags=[kind_key.capitalize()])

    def refuse(error: JobStoreError):
        raise HTTPException(status_code=error.status, detail=str(error))

    @router.get("", summary=f"Search {kind_key}")
    def search(request: Request, limit: int = Query(store.MAX_RESULTS, ge=1, le=store.MAX_RESULTS),
               db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
        return store.search(db, kind, dict(request.query_params), limit)

    @router.get("/{name:path}", summary=f"One {kind.singular}, with its variables and what uses it")
    def get_one(name: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
        try:
            return store.describe(kind, store.find(db, kind, name), db)
        except JobStoreError as e:
            refuse(e)

    @router.put("/{name:path}", summary=f"Change a {kind.singular}")
    def change(name: str, payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)) -> Dict[str, Any]:
        try:
            obj, changes = store.update(db, kind, name, payload, EDITOR_NAME)
        except JobStoreError as e:
            db.rollback()
            refuse(e)
        return {"item": store.describe(kind, obj, db), "changes": changes}

    @router.delete("/{name:path}", status_code=status.HTTP_204_NO_CONTENT, summary=f"Delete a {kind.singular} nothing uses")
    def remove(name: str, db: Session = Depends(get_db)):
        try:
            store.delete(db, kind, name, EDITOR_NAME)
        except JobStoreError as e:
            db.rollback()
            refuse(e)

    return router


routers = [make_router(key) for key in store.KINDS]

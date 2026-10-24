"""
Alerts (docs/WORKFLOWS_PHASE8.md): who is told, and what they are told, when a Reaction's Notify fires.

    GET    /api/v1/alerts                    every alert, with the Reactions that name it
    POST   /api/v1/alerts                    add one: name, description, subject, message, recipients
    GET    /api/v1/alerts/{name}             one alert
    PUT    /api/v1/alerts/{name}             change it; fields left out stay as they are
    DELETE /api/v1/alerts/{name}             remove it, if no Reaction names it
    POST   /api/v1/alerts/{name}/test        Send a test: queues the alert's message, marked as a test
    GET    /api/v1/alert-deliveries          the messages, newest first (status, alert, limit)
    GET    /api/v1/mail-settings             where mail is sent through
    PUT    /api/v1/mail-settings             change that

Nothing here sends mail. A message is queued as PENDING and the sender inside the server sends it (app/mail_sender.py).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import alert_outbox, alert_store as store
from app.database import get_db
from app.job_store import JobStoreError

router = APIRouter(prefix="/api/v1", tags=["Alerts"])


def _refuse(error: JobStoreError):
    raise HTTPException(status_code=error.status, detail=str(error))


@router.get("/alerts", summary="Every alert")
def list_alerts(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return store.search(db)


@router.post("/alerts", status_code=status.HTTP_201_CREATED, summary="Add an alert")
def add_alert(payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return store.describe(db, store.create(db, payload))
    except JobStoreError as e:
        db.rollback()
        _refuse(e)


@router.get("/alerts/{name}", summary="One alert")
def get_alert(name: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return store.describe(db, store.find(db, name))
    except JobStoreError as e:
        _refuse(e)


@router.put("/alerts/{name}", summary="Change an alert")
def change_alert(name: str, payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return store.describe(db, store.update(db, name, payload))
    except JobStoreError as e:
        db.rollback()
        _refuse(e)


@router.delete("/alerts/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an alert no Reaction names")
def remove_alert(name: str, db: Session = Depends(get_db)):
    try:
        store.delete(db, name)
    except JobStoreError as e:
        db.rollback()
        _refuse(e)


@router.post("/alerts/{name}/test", summary="Send a test: queue the alert's message, marked as a test")
def send_test(name: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        alert = store.find(db, name)
    except JobStoreError as e:
        _refuse(e)
    delivery = alert_outbox.queue_test(db, alert)
    db.commit()
    return store.delivery_out(delivery)


@router.get("/alert-deliveries", summary="The messages Notify queued, newest first")
def list_deliveries(status: Optional[str] = Query(None, description="PENDING, SENT or FAILED"),
                    alert: Optional[str] = Query(None, description="One alert's name"),
                    limit: int = Query(100, ge=1, le=store.MAX_DELIVERIES),
                    db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return store.deliveries(db, status, alert, limit)


@router.get("/mail-settings", summary="Where mail is sent through")
def get_mail_settings(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return store.mail_settings(db)


@router.put("/mail-settings", summary="Change where mail is sent through")
def change_mail_settings(payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return store.save_mail_settings(db, payload)
    except JobStoreError as e:
        db.rollback()
        _refuse(e)

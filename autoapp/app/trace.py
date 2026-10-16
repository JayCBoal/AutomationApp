"""
The operations log and the file trace.

An Operation is one file handled by one step. The trace links operations into a
file's route by location: an operation that read a file from a path follows the
operation that last wrote that file to that path. This works across steps and
across jobs, and through renames, because each hop is matched on its own
source and destination.

An operation with no file (a SQL statement, say) is in the log but has no route:
its trace is just itself.

A filename that recurs (the same name every day, say) is told apart by time: a
read belongs to the most recent write before it, and a write's readers end at
the next write to the same place, or at the operation that moved the file away.
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, aliased

from app.models import Application, Endpoint, Entity, JobRun, Operation, Site
from app.schemas import FileLocation, FileTrace, OperationOut, TraceHop

MAX_RESULTS = 500


def _location(endpoint: Optional[Endpoint], path, filename, size) -> FileLocation:
    location = FileLocation(path=path, filename=filename, size=size)
    if endpoint:
        location.endpoint = endpoint.Name
        location.application = endpoint.application.Name if endpoint.application else None
        if endpoint.site:
            location.site = endpoint.site.Name
            location.entity = endpoint.site.entity.Name if endpoint.site.entity else None
    return location


def describe(op: Operation) -> dict:
    """An operation in the shape the API returns, with both locations spelled out."""
    return dict(
        id=op.id,
        op_type=op.OpType,
        status=op.OpStatus,
        source=_location(op.source_endpoint, op.SourcePath, op.SourceFilename, op.SourceSize),
        dest=_location(op.dest_endpoint, op.DestPath, op.DestFilename, op.DestSize),
        checksum=op.Checksum,
        details=json.loads(op.Details) if op.Details else None,
        error=op.ErrorMessage,
        started=op.StartedDateTime,
        ended=op.EndedDateTime,
        job_key=op.run.JobKey,
        instance_id=op.run.SchedulerInstanceID,
        run_number=op.run.RunNumber,
        scheduler=op.run.SchedulerName,
        run_id=op.run.RunID,
        step_order=op.StepOrder,
    )


def search_operations(
    db: Session,
    filename: Optional[str] = None,
    endpoint: Optional[str] = None,
    source_endpoint: Optional[str] = None,
    source_path: Optional[str] = None,
    source_filename: Optional[str] = None,
    source_application: Optional[str] = None,
    source_entity: Optional[str] = None,
    source_site: Optional[str] = None,
    dest_endpoint: Optional[str] = None,
    dest_path: Optional[str] = None,
    dest_filename: Optional[str] = None,
    dest_application: Optional[str] = None,
    dest_entity: Optional[str] = None,
    dest_site: Optional[str] = None,
    application: Optional[str] = None,
    entity: Optional[str] = None,
    site: Optional[str] = None,
    job_key: Optional[str] = None,
    instance_id: Optional[str] = None,
    scheduler: Optional[str] = None,
    op_type: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = MAX_RESULTS,
) -> List[OperationOut]:
    """
    Finds operations, newest first. Text criteria ignore case and match anywhere
    in the field. filename, endpoint, application, entity and site match either
    side of the operation; the source_ and dest_ criteria match one side only.
    The instance ID, operation type and status must match exactly.
    """
    def contains(column, value):
        return column.ilike(f"%{value}%")

    # Each side's endpoint, and through it the application, the site and the site's entity
    sides = {}
    query = db.query(Operation).join(JobRun, Operation.JobRun_id == JobRun.id)
    for side, endpoint_id in (("source", Operation.SourceEndpoint_id), ("dest", Operation.DestEndpoint_id)):
        ep = aliased(Endpoint)
        app, site_, entity_ = Application.__table__.alias(), Site.__table__.alias(), Entity.__table__.alias()
        query = (
            query.outerjoin(ep, endpoint_id == ep.MasterObject_id)
            .outerjoin(app, ep.Application_MasterObject_id == app.c.MasterObject_id)
            .outerjoin(site_, ep.Site_MasterObject_id == site_.c.MasterObject_id)
            .outerjoin(entity_, site_.c.Entity_MasterObject_id == entity_.c.MasterObject_id)
        )
        sides[side] = dict(endpoint=ep.Name, application=app.c.Name, site=site_.c.Name, entity=entity_.c.Name)
    source, dest = sides["source"], sides["dest"]

    either_side = [
        (filename, Operation.SourceFilename, Operation.DestFilename),
        (endpoint, source["endpoint"], dest["endpoint"]),
        (application, source["application"], dest["application"]),
        (entity, source["entity"], dest["entity"]),
        (site, source["site"], dest["site"]),
    ]
    for value, source_column, dest_column in either_side:
        if value:
            query = query.filter(or_(contains(source_column, value), contains(dest_column, value)))

    one_side = [
        (source_endpoint, source["endpoint"]), (source_path, Operation.SourcePath),
        (source_filename, Operation.SourceFilename),
        (source_application, source["application"]), (source_entity, source["entity"]), (source_site, source["site"]),
        (dest_endpoint, dest["endpoint"]), (dest_path, Operation.DestPath),
        (dest_filename, Operation.DestFilename),
        (dest_application, dest["application"]), (dest_entity, dest["entity"]), (dest_site, dest["site"]),
        (job_key, JobRun.JobKey),
        (scheduler, JobRun.SchedulerName),
    ]
    for value, column in one_side:
        if value:
            query = query.filter(contains(column, value))

    if instance_id:
        query = query.filter(JobRun.SchedulerInstanceID == instance_id)
    if op_type:
        query = query.filter(Operation.OpType == op_type.upper())
    if status:
        query = query.filter(Operation.OpStatus == status.upper())
    if date_from:
        query = query.filter(Operation.EndedDateTime >= date_from)
    if date_to:
        query = query.filter(Operation.EndedDateTime <= date_to)

    rows = (
        query.order_by(Operation.EndedDateTime.desc(), Operation.JobRun_id.desc(), Operation.Seq.desc())
        .limit(max(1, min(limit, MAX_RESULTS)))
        .all()
    )
    return [OperationOut(**describe(op)) for op in rows]


def _when(op: Operation):
    """Sort key putting operations in the order they happened."""
    return (op.EndedDateTime or datetime.min, op.JobRun_id, op.Seq)


def _writes_to(db: Session, path, filename) -> List[Operation]:
    return db.query(Operation).filter(
        and_(Operation.DestPath == path, Operation.DestFilename == filename, Operation.OpStatus == "SUCCESS")
    ).all()


# Operations after which the file is no longer where it was read from
CONSUMING = {"MOVE", "DELETE", "ZIP_MOVE"}


def _same_step(a: Operation, b: Operation) -> bool:
    """Operations of one step in one run. Several files zipped into one archive are one write of it."""
    return a.JobRun_id == b.JobRun_id and a.StepOrder == b.StepOrder


def _is_zip(op: Operation) -> bool:
    return op.OpType in ("ZIP", "ZIP_MOVE")


def _carried(op: Operation, member: Optional[str]) -> Optional[str]:
    """
    Which file inside an archive the trace is following once it reaches this operation.
    A zip starts it (the file it put in); an unzip ends it; anything else passes it on.
    """
    if _is_zip(op):
        return op.SourceFilename
    if op.OpType == "UNZIP":
        return None
    return member


def _readers(db: Session, write: Operation, member: Optional[str] = None) -> List[Operation]:
    """
    The operations that picked up the file this operation wrote, in order. When the
    file is an archive and the trace is following one file inside it (member), only
    the unzip that took that file out counts.
    """
    if write.OpStatus != "SUCCESS" or not write.DestFilename:
        return []
    path, filename = write.DestPath, write.DestFilename
    member = _carried(write, member)
    later_writes = [w for w in _writes_to(db, path, filename) if _when(w) > _when(write) and not _same_step(w, write)]
    replaced_at = min((_when(w) for w in later_writes), default=None)

    reads = db.query(Operation).filter(
        and_(Operation.SourcePath == path, Operation.SourceFilename == filename)
    ).all()
    readers = []
    for read in sorted(reads, key=_when):
        if _when(read) <= _when(write):
            continue
        if replaced_at and _when(read) > replaced_at:
            break
        if read.OpType == "UNZIP" and member and os.path.basename(read.DestFilename or "") != member:
            continue    # another file out of the same archive
        readers.append(read)
        if read.OpType in CONSUMING and read.OpStatus == "SUCCESS":
            break   # the file is no longer there for anything later to read
    return readers


def _predecessor(db: Session, op: Operation, member: Optional[str] = None) -> Optional[Operation]:
    """
    The operation that put the file where this one found it, if RunMyFiles recorded one.
    Where several files were zipped into one archive, the one followed is the member
    the trace came out with; with none to go on, the trace starts at the archive.
    """
    if not op.SourceFilename:
        return None     # not a file operation, so there is no file to follow
    if op.OpType == "UNZIP":
        member = os.path.basename(op.DestFilename or "") or None
    earlier_writes = [w for w in _writes_to(db, op.SourcePath, op.SourceFilename) if _when(w) < _when(op)]
    if not earlier_writes:
        return None
    latest = max(earlier_writes, key=_when)
    siblings = [w for w in earlier_writes if _same_step(w, latest)]
    if len(siblings) > 1:
        matching = [w for w in siblings if member and w.SourceFilename == member]
        if not matching:
            return None
        latest = max(matching, key=_when)
    return latest if any(r.id == op.id for r in _readers(db, latest, member)) else None


def trace_operation(db: Session, operation_id: int) -> Optional[FileTrace]:
    """
    The whole route of the file an operation handled: back to where it first
    entered, then forward through every operation that carried it on. A file
    copied to two places has two branches; each hop names the hop it follows.
    A file zipped with others shares the archive's hops, and only its own unzip.
    Returns None if there is no such operation.
    """
    start = db.get(Operation, operation_id)
    if not start:
        return None

    root, seen, member = start, {start.id}, None
    while True:
        previous = _predecessor(db, root, member)
        if not previous or previous.id in seen:
            break
        if root.OpType == "UNZIP":
            member = os.path.basename(root.DestFilename or "") or None
        elif _is_zip(previous):
            member = None
        root = previous
        seen.add(root.id)

    follows: Dict[int, Optional[int]] = {root.id: None}
    found: Dict[int, Operation] = {root.id: root}
    queue = [(root, None)]
    while queue:
        current, member = queue.pop(0)
        for reader in _readers(db, current, member):
            if reader.id not in found:
                found[reader.id] = reader
                follows[reader.id] = current.id
                queue.append((reader, _carried(current, member)))

    hops = [TraceHop(**describe(op), follows=follows[op.id]) for op in sorted(found.values(), key=_when)]
    return FileTrace(filename=start.DestFilename or start.SourceFilename, hops=hops)

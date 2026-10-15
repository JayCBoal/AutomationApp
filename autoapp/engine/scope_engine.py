import os
import re
from engine.date_mask import format_date
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from app.models import Application, Entity, Job, Variable
from engine import settings, tag_vars


class ScopeResolutionEngine:
    """
    Evaluates variable scope inheritance and interpolates dynamic placeholders.

    The levels, lowest priority first by default (the VariablePrecedence setting):

        SYS        system values
        ENTITY     the endpoint's entity: its tags' variables, then its own
        APP        the endpoint's application: its tags' variables, then its own
        ENDPOINT   the endpoint's tags
        TAG        the job's tags
        JOB        the job's own variables

    ENTITY, APP and ENDPOINT apply only while an endpoint's path and pattern are
    being filled in. A variable two tags on one object disagree about is a
    conflict at that level; using it, unless a higher level gives it a value, is
    an error (see engine/tag_vars.py).
    """

    # Matches ${SCOPE:target.var}, ${SCOPE.var}, or ${var}. A tag is named by its path: ${TAG:Finance/Reporting.Var}
    EXPLICIT_TARGET_PATTERN = re.compile(
        r"\$\{(APP|ENTITY|TAG):([^.}]+)\.([^}]+)\}"
    )
    EXPLICIT_SCOPE_PATTERN = re.compile(
        r"\$\{(SYS|APP|ENTITY|JOB)\.([^}]+)\}"
    )
    IMPLICIT_VAR_PATTERN = re.compile(r"\$\{([a-zA-Z0-9_:]+)\}")
    # ${DATE:yyyyMMdd}: the moment the run started, in the format the mask gives (see engine/date_mask.py)
    DATE_PATTERN = re.compile(r"\$\{DATE:([^}]*)\}")
    ANY_PLACEHOLDER_PATTERN = re.compile(r"\$\{[^}]+\}")

    # A variable's value may itself contain placeholders; stop after this many passes
    MAX_NESTING_DEPTH = 10


    def __init__(
        self,
        db: Session,
        job_id: int,
        instance_id: str,
        global_config: Optional[Dict[str, Any]] = None,
    ):
        self.db = db
        self.job_id = job_id
        self.instance_id = instance_id
        self.global_config = global_config or {}

        # Isolated scope caches for targeted lookup
        self.scoped_vars: Dict[str, Dict[str, Any]] = {
            "SYS": {},
            "APP": {},
            "ENTITY": {},
            "ENDPOINT": {},
            "JOB": {},
            "TAG": {},      # what the job's tags give
            "TARGETED": {
                "APP": {},
                "ENTITY": {},
            },  # Named object overrides
        }

        # Variables that tags on one object disagree about, by level
        self.conflicts: Dict[str, Dict[str, tag_vars.Conflict]] = {level: {} for level in self.scoped_vars}
        # The tags a ${TAG:path.Var} may name: the job's and their ancestors
        self.reachable_tags: Dict[str, Any] = {}

        # Merged cascade dictionary, and the conflicts no higher level settles
        self.resolved_cascade: Dict[str, Any] = {}
        self.resolved_conflicts: Dict[str, tag_vars.Conflict] = {}

    @property
    def working_folder(self) -> Optional[str]:
        """The job's working folder (${SYS:WORKING_FOLDER}), or None if no working root is configured."""
        return self.scoped_vars["SYS"].get("WORKING_FOLDER")

    def _get_variables_for_master_object(
        self, master_object_id: int
    ) -> Dict[str, Any]:
        """Fetches key-value variable records tied to a MasterObject_id."""
        if not master_object_id:
            return {}
        vars_records = (
            self.db.query(Variable)
            .filter(Variable.MasterObject_id == master_object_id)
            .all()
        )
        return {v.VarName: v.VarValue for v in vars_records}

    def _with_tags(self, master_object_id: Optional[int]):
        """An object's variables over those its tags give, and the conflicts its own do not settle."""
        own = self._get_variables_for_master_object(master_object_id)
        given = tag_vars.inherited(self.db, master_object_id)
        conflicts = {name: c for name, c in given.conflicts.items() if name not in own}
        return {**given.plain(), **own}, conflicts

    def build_context(self) -> Dict[str, Any]:
        """Populates scope caches and eager-merges the execution context dictionary."""
        now = datetime.now()
        self.started = now      # every date placeholder in the run shows this one moment

        # 1. System Scope (${SYS:...})
        self.scoped_vars["SYS"] = {
            "YYYYMMDD": now.strftime("%Y%m%d"),
            "INSTANCE_ID": self.instance_id,
            "TIMESTAMP": now.isoformat(),
        }
        self.scoped_vars["SYS"].update(self.global_config)

        # 2. Retrieve Job
        job: Optional[Job] = (
            self.db.query(Job).filter(Job.MasterObject_id == self.job_id).first()
        )
        if not job:
            raise ValueError(f"Job with MasterObject_id {self.job_id} not found.")

        # 3. Working folder: <working root>/<JobKey>, private to the job
        working_root = self.global_config.get("WORKING_ROOT") or os.environ.get("AUTOAPP_WORKING_ROOT")
        if working_root:
            self.scoped_vars["SYS"]["WORKING_FOLDER"] = os.path.join(working_root, job.JobKey)

        # 4. Populate Associated Scopes
        # ENTITY and APP belong to an Endpoint, not to the job; see interpolate(text, endpoint=...)
        self.scoped_vars["JOB"] = self._get_variables_for_master_object(
            job.MasterObject_id
        )

        # 5. The job's tags, with what they inherit from their parents
        job_tags = tag_vars.inherited(self.db, job.MasterObject_id)
        self.scoped_vars["TAG"] = job_tags.plain()
        self.conflicts["TAG"] = job_tags.conflicts
        self.reachable_tags = tag_vars.reachable(job_tags.tags)

        # 6. Merge the levels, in the order the VariablePrecedence setting gives
        self.precedence = self.global_config.get("CASCADE_PRECEDENCE") or settings.current(self.db, "VariablePrecedence")
        self.resolved_cascade, self.resolved_conflicts = self._merge_cascade()
        return self.resolved_cascade

    def _merge_cascade(self):
        """
        Merges the levels into one dictionary, lowest priority first. A conflict at
        one level hides what a lower level gives, and a value at a higher level settles it.
        """
        merged: Dict[str, Any] = {}
        unsettled: Dict[str, tag_vars.Conflict] = {}
        for scope in self.precedence:
            for name, conflict in self.conflicts.get(scope, {}).items():
                merged.pop(name, None)
                unsettled[name] = conflict
            for name, value in self.scoped_vars.get(scope, {}).items():
                merged[name] = value
                unsettled.pop(name, None)
        return merged, unsettled

    @contextmanager
    def _endpoint_scope(self, endpoint: Any):
        """
        Temporarily fills the APP and ENTITY scopes from an Endpoint.
        Applications attach directly to Endpoints; Entities attach via Sites (Endpoint -> Site -> Entity).
        """
        levels = ("APP", "ENTITY", "ENDPOINT")
        saved = ({level: self.scoped_vars[level] for level in levels}, {level: self.conflicts[level] for level in levels},
                 self.resolved_cascade, self.resolved_conflicts)

        app = endpoint.application
        entity = endpoint.site.entity if endpoint.site else None
        self.scoped_vars["APP"], self.conflicts["APP"] = self._with_tags(app.MasterObject_id) if app else ({}, {})
        self.scoped_vars["ENTITY"], self.conflicts["ENTITY"] = (
            self._with_tags(entity.MasterObject_id) if entity else ({}, {}))
        endpoint_tags = tag_vars.inherited(self.db, endpoint.MasterObject_id)
        self.scoped_vars["ENDPOINT"], self.conflicts["ENDPOINT"] = endpoint_tags.plain(), endpoint_tags.conflicts
        self.resolved_cascade, self.resolved_conflicts = self._merge_cascade()
        try:
            yield
        finally:
            variables, conflicts, self.resolved_cascade, self.resolved_conflicts = saved
            self.scoped_vars.update(variables)
            self.conflicts.update(conflicts)

    def _fetch_explicit_target_var(
        self, scope_type: str, target_name: str, var_name: str
    ) -> Optional[str]:
        """
        Fetches a variable of a named object (e.g., ${ENTITY:JAYCO.TaxID}), its tags' included.
        A tag must be one the job carries, or an ancestor of one.
        """
        if scope_type == "TAG":
            path = tag_vars.SEPARATOR.join(part.strip() for part in target_name.split(tag_vars.SEPARATOR))
            tag = self.reachable_tags.get(path)
            if tag is None:
                raise ValueError(f"${{TAG:{target_name}.{var_name}}} names tag '{tag_vars.shown(path)}', "
                                 f"which is not one of this job's tags or their parents.")
            given = tag_vars.variables_of(tag).get(var_name)
            return given.value if given else None

        model_map = {"APP": Application, "ENTITY": Entity}
        if scope_type in model_map:
            # Check internal cache first
            if target_name not in self.scoped_vars["TARGETED"][scope_type]:
                obj = (
                    self.db.query(model_map[scope_type])
                    .filter(model_map[scope_type].Name == target_name)
                    .first()
                )
                self.scoped_vars["TARGETED"][scope_type][target_name] = (
                    self._with_tags(obj.MasterObject_id) if obj else ({}, {}))

            values, conflicts = self.scoped_vars["TARGETED"][scope_type][target_name]
            if var_name not in values and var_name in conflicts:
                raise ValueError(conflicts[var_name].message())
            return values.get(var_name)

        return None

    def interpolate(self, text: str, endpoint: Optional[Any] = None, leave: tuple = ()) -> str:
        """
        Interpolates placeholders matching ${...} syntax, including placeholders
        inside variable values. Raises ValueError if any placeholder cannot be resolved.

        When an Endpoint is given, ${APP.x} and ${ENTITY.x} (and the implicit cascade)
        resolve against that Endpoint's Application and its Site's Entity.

        leave names placeholder kinds to be left as written, for something later to fill
        in: leave=("FILE",) keeps ${FILE:NAME} for the step handler, which knows the file.
        """
        if not isinstance(text, str) or "${" not in text:
            return text

        if endpoint is not None:
            with self._endpoint_scope(endpoint):
                return self._interpolate(text, leave)
        return self._interpolate(text, leave)

    def _interpolate(self, text: str, leave: tuple = ()) -> str:
        original = text
        for _ in range(self.MAX_NESTING_DEPTH):
            resolved = self._interpolate_once(text)
            if resolved == text:
                break
            text = resolved
        else:
            raise ValueError(
                f"Placeholders in '{original}' are nested more than {self.MAX_NESTING_DEPTH} levels deep "
                f"(circular variable reference?)"
            )

        unresolved = sorted(
            placeholder for placeholder in set(self.ANY_PLACEHOLDER_PATTERN.findall(text))
            if not any(placeholder.startswith("${" + kind + ":") for kind in leave)
        )
        if unresolved:
            raise ValueError(f"Unresolved placeholder(s) in '{original}': {', '.join(unresolved)}")

        return text

    def _interpolate_once(self, text: str) -> str:
        """Single substitution pass; unknown placeholders are left in place."""
        # 0. Dates: ${DATE:yyyyMMdd}. A mask that is not understood raises ValueError.
        text = self.DATE_PATTERN.sub(lambda match: format_date(match.group(1), self.started), text)

        # 1. Resolve Explicit Targeted Syntax: ${SCOPE:TargetName.VarName}
        def replace_explicit_target(match):
            scope_type, target_name, var_name = (
                match.group(1),
                match.group(2),
                match.group(3),
            )
            val = self._fetch_explicit_target_var(
                scope_type, target_name, var_name
            )
            return str(val) if val is not None else match.group(0)

        text = self.EXPLICIT_TARGET_PATTERN.sub(replace_explicit_target, text)

        # 2. Resolve Associated Scope Syntax: ${SCOPE.VarName}
        def replace_explicit_scope(match):
            scope_key, var_name = match.group(1), match.group(2)
            val = self.scoped_vars.get(scope_key, {}).get(var_name)
            if val is None and var_name in self.conflicts.get(scope_key, {}):
                raise ValueError(self.conflicts[scope_key][var_name].message())
            return str(val) if val is not None else match.group(0)

        text = self.EXPLICIT_SCOPE_PATTERN.sub(replace_explicit_scope, text)

        # 3. Resolve Implicit Cascade Variables & Macros: ${VarName} or ${SYS:YYYYMMDD}
        def replace_implicit_var(match):
            var_key = match.group(1)
            if var_key.startswith("SYS:"):
                sys_key = var_key.split(":", 1)[1]
                val = self.scoped_vars["SYS"].get(sys_key)
                return str(val) if val is not None else match.group(0)

            if var_key in self.resolved_conflicts:
                raise ValueError(self.resolved_conflicts[var_key].message())
            if var_key in self.resolved_cascade:
                return str(self.resolved_cascade[var_key])

            return match.group(0)

        text = self.IMPLICIT_VAR_PATTERN.sub(replace_implicit_var, text)

        return text
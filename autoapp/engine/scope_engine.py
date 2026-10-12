import os
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from app.models import Application, Entity, Job, MasterObject, Process, Tag, Variable


class ScopeResolutionEngine:
    """Evaluates variable scope inheritance and interpolates dynamic placeholders."""

    # Matches ${SCOPE:target.var}, ${SCOPE.var}, or ${var}
    EXPLICIT_TARGET_PATTERN = re.compile(
        r"\$\{(APP|ENTITY|PROC|JOB|TAG):([^.]+)\.([^}]+)\}"
    )
    EXPLICIT_SCOPE_PATTERN = re.compile(
        r"\$\{(SYS|APP|ENTITY|PROC|JOB)\.([^}]+)\}"
    )
    IMPLICIT_VAR_PATTERN = re.compile(r"\$\{([a-zA-Z0-9_:]+)\}")
    ANY_PLACEHOLDER_PATTERN = re.compile(r"\$\{[^}]+\}")

    # A variable's value may itself contain placeholders; stop after this many passes
    MAX_NESTING_DEPTH = 10

    # Default hierarchy precedence (Low priority -> High priority)
    DEFAULT_PRECEDENCE = ["SYS", "ENTITY", "APP", "PROC", "TAG", "JOB"]

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
            "PROC": {},
            "JOB": {},
            "TAG": {},  # Format: {"TagName": {"VarName": "Value"}}
            "TARGETED": {
                "APP": {},
                "ENTITY": {},
            },  # Named object overrides
        }

        # Merged cascade dictionary
        self.resolved_cascade: Dict[str, Any] = {}
        self._tag_cascade_vars: Dict[str, Any] = {}

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

    def _resolve_tag_hierarchy_root_to_leaf(self, tag: Tag) -> List[Tag]:
        """Traverses tag parents from Root down to Leaf."""
        chain = []
        curr = tag
        while curr:
            chain.append(curr)
            curr = getattr(curr, "parent_tag", None)
        return list(reversed(chain))

    def build_context(self) -> Dict[str, Any]:
        """Populates scope caches and eager-merges the execution context dictionary."""
        now = datetime.now()

        # 1. System Scope (${SYS:...})
        self.scoped_vars["SYS"] = {
            "YYYYMMDD": now.strftime("%Y%m%d"),
            "INSTANCE_ID": self.instance_id,
            "TIMESTAMP": now.isoformat(),
        }
        self.scoped_vars["SYS"].update(self.global_config)

        # 2. Retrieve Job and Process
        job: Optional[Job] = (
            self.db.query(Job).filter(Job.MasterObject_id == self.job_id).first()
        )
        if not job:
            raise ValueError(f"Job with MasterObject_id {self.job_id} not found.")

        process: Optional[Process] = job.process

        # 3. Working folder: <working root>/<process name>, shared by the jobs of a process
        working_root = self.global_config.get("WORKING_ROOT") or os.environ.get("AUTOAPP_WORKING_ROOT")
        if working_root and process:
            self.scoped_vars["SYS"]["WORKING_FOLDER"] = os.path.join(working_root, process.Name)

        # 4. Populate Associated Scopes
        # ENTITY and APP belong to an Endpoint, not to the job; see interpolate(text, endpoint=...)
        if process:
            self.scoped_vars["PROC"] = self._get_variables_for_master_object(
                process.MasterObject_id
            )
        self.scoped_vars["JOB"] = self._get_variables_for_master_object(
            job.MasterObject_id
        )

        # 5. Resolve Tags (Root -> Leaf merge)
        associated_tags: List[Tag] = []
        for obj in [process, job]:
            if obj and hasattr(obj, "tags"):
                associated_tags.extend(obj.tags)

        self._tag_cascade_vars = {}
        for tag in associated_tags:
            tag_chain = self._resolve_tag_hierarchy_root_to_leaf(tag)
            for t in tag_chain:
                t_vars = self._get_variables_for_master_object(
                    t.MasterObject_id
                )
                tag_name = getattr(t, "TagName", getattr(t, "Name", str(t.MasterObject_id)))
                self.scoped_vars["TAG"][tag_name] = t_vars
                self._tag_cascade_vars.update(t_vars)

        # 6. Eager Context Dict Merge based on Configurable Precedence
        self.resolved_cascade = self._merge_cascade()
        return self.resolved_cascade

    def _merge_cascade(self) -> Dict[str, Any]:
        """Merges the scope caches into one dictionary, lowest priority first."""
        precedence = self.global_config.get(
            "CASCADE_PRECEDENCE", self.DEFAULT_PRECEDENCE
        )
        merged: Dict[str, Any] = {}
        for scope in precedence:
            if scope == "TAG":
                merged.update(self._tag_cascade_vars)
            elif scope in self.scoped_vars:
                merged.update(self.scoped_vars[scope])
        return merged

    @contextmanager
    def _endpoint_scope(self, endpoint: Any):
        """
        Temporarily fills the APP and ENTITY scopes from an Endpoint.
        Applications attach directly to Endpoints; Entities attach via Sites (Endpoint -> Site -> Entity).
        """
        saved = (self.scoped_vars["APP"], self.scoped_vars["ENTITY"], self.resolved_cascade)

        app = endpoint.application
        entity = endpoint.site.entity if endpoint.site else None
        self.scoped_vars["APP"] = self._get_variables_for_master_object(app.MasterObject_id) if app else {}
        self.scoped_vars["ENTITY"] = self._get_variables_for_master_object(entity.MasterObject_id) if entity else {}
        self.resolved_cascade = self._merge_cascade()
        try:
            yield
        finally:
            self.scoped_vars["APP"], self.scoped_vars["ENTITY"], self.resolved_cascade = saved

    def _fetch_explicit_target_var(
        self, scope_type: str, target_name: str, var_name: str
    ) -> Optional[str]:
        """Lazy-fetches explicit non-associated target objects (e.g., ${ENTITY:JAYCO.TaxID})."""
        if scope_type == "TAG":
            return self.scoped_vars["TAG"].get(target_name, {}).get(var_name)

        model_map = {"APP": Application, "ENTITY": Entity}
        if scope_type in model_map:
            # Check internal cache first
            if target_name not in self.scoped_vars["TARGETED"][scope_type]:
                obj = (
                    self.db.query(model_map[scope_type])
                    .filter(model_map[scope_type].Name == target_name)
                    .first()
                )
                if obj:
                    self.scoped_vars["TARGETED"][scope_type][
                        target_name
                    ] = self._get_variables_for_master_object(
                        obj.MasterObject_id
                    )
                else:
                    self.scoped_vars["TARGETED"][scope_type][target_name] = {}

            return (
                self.scoped_vars["TARGETED"][scope_type]
                .get(target_name, {})
                .get(var_name)
            )

        return None

    def interpolate(self, text: str, endpoint: Optional[Any] = None) -> str:
        """
        Interpolates placeholders matching ${...} syntax, including placeholders
        inside variable values. Raises ValueError if any placeholder cannot be resolved.

        When an Endpoint is given, ${APP.x} and ${ENTITY.x} (and the implicit cascade)
        resolve against that Endpoint's Application and its Site's Entity.
        """
        if not isinstance(text, str) or "${" not in text:
            return text

        if endpoint is not None:
            with self._endpoint_scope(endpoint):
                return self._interpolate(text)
        return self._interpolate(text)

    def _interpolate(self, text: str) -> str:
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

        unresolved = sorted(set(self.ANY_PLACEHOLDER_PATTERN.findall(text)))
        if unresolved:
            raise ValueError(f"Unresolved placeholder(s) in '{original}': {', '.join(unresolved)}")

        return text

    def _interpolate_once(self, text: str) -> str:
        """Single substitution pass; unknown placeholders are left in place."""
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
            return str(val) if val is not None else match.group(0)

        text = self.EXPLICIT_SCOPE_PATTERN.sub(replace_explicit_scope, text)

        # 3. Resolve Implicit Cascade Variables & Macros: ${VarName} or ${SYS:YYYYMMDD}
        def replace_implicit_var(match):
            var_key = match.group(1)
            if var_key.startswith("SYS:"):
                sys_key = var_key.split(":", 1)[1]
                val = self.scoped_vars["SYS"].get(sys_key)
                return str(val) if val is not None else match.group(0)

            if var_key in self.resolved_cascade:
                return str(self.resolved_cascade[var_key])

            return match.group(0)

        text = self.IMPLICIT_VAR_PATTERN.sub(replace_implicit_var, text)

        return text
import datetime
import re
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Integer, String, Text, Boolean, Date, DateTime, ForeignKey, Enum, UniqueConstraint,
    false, func, text, true
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import backref, declarative_base, relationship, validates

Base = declarative_base()

# A plain DATETIME on MariaDB and MySQL keeps whole seconds only, and the file trace orders operations by time
PreciseDateTime = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")

# Each default is declared twice: "default" is applied by this code, "server_default" by the
# database itself, so that rows inserted with plain SQL (a seed script, a DBA) get it too.


def utcnow():
    """Current UTC time without timezone info, which is how every DateTime column here is stored."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


# ============================================================================
# MasterObject Polymorphic Base Model
# ============================================================================
class MasterObject(Base):
    __tablename__ = 'MasterObjects'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ObjectType = Column(
        Enum('APPLICATION', 'ENTITY', 'SITE', 'CREDENTIAL', 'TAG', 'JOB', 'ENDPOINT', 'SCHEDULER',
             name='object_type_enum'),
        nullable=False
    )
    CreatedDateTime = Column(DateTime, default=utcnow, server_default=func.now())
    CreatedBy = Column(String(100), default='system', server_default='system')
    ModifiedDateTime = Column(DateTime, onupdate=utcnow)
    ModifiedBy = Column(String(100), nullable=True)

    __mapper_args__ = {
        'polymorphic_on': ObjectType,
        'polymorphic_identity': 'MASTER_OBJECT'
    }

    # Universal One-to-Many Relationships attached to ANY MasterObject
    variables = relationship("Variable", backref="owner", cascade="all, delete-orphan", passive_deletes=True)
    tag_assignments = relationship("TagAssignment", backref="target_object", cascade="all, delete-orphan", passive_deletes=True)


# ============================================================================
# Master Domain Subtypes (Inheriting from MasterObject)
# ============================================================================
class Application(MasterObject):
    __tablename__ = 'Applications'

    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), primary_key=True)
    Name = Column(String(100), nullable=False, unique=True)
    Abbr = Column(String(10), nullable=False, unique=True)
    Description = Column(Text, nullable=True)
    IsActive = Column(Boolean, default=True, server_default=true())

    __mapper_args__ = {
        'polymorphic_identity': 'APPLICATION',
    }


class Entity(MasterObject):
    __tablename__ = "Entities"

    MasterObject_id = Column(Integer, ForeignKey("MasterObjects.id", ondelete="CASCADE"), primary_key=True)
    Name = Column(String(64), nullable=False, unique=True)
    Abbr = Column(String(10), nullable=False)
    Description = Column(String(256), nullable=True)
    IsActive = Column(Boolean, default=True, server_default=true())

    # Explicitly define foreign_keys to resolve ambiguity with Endpoint references
    sites = relationship(
        "Site",
        foreign_keys="[Site.Entity_MasterObject_id]",
        back_populates="entity",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    __mapper_args__ = {
        'polymorphic_identity': 'ENTITY',
    }


class Site(MasterObject):
    __tablename__ = "Sites"

    MasterObject_id = Column(Integer, ForeignKey("MasterObjects.id", ondelete="CASCADE"), primary_key=True)
    Entity_MasterObject_id = Column(Integer, ForeignKey("Entities.MasterObject_id", ondelete="SET NULL"), nullable=True)
    Name = Column(String(64), nullable=False, unique=True)
    Host = Column(String(128), nullable=False)
    Port = Column(Integer, default=22, server_default=text('22'))
    Protocol = Column(String(16), default="SFTP", server_default="SFTP")
    Description = Column(String(256), nullable=True)
    IsActive = Column(Boolean, default=True, server_default=true())

    entity = relationship(
        "Entity",
        foreign_keys=[Entity_MasterObject_id],
        back_populates="sites",
    )

    __mapper_args__ = {
        'polymorphic_identity': 'SITE',
    }


class Credential(MasterObject):
    __tablename__ = 'Credentials'

    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), primary_key=True)
    Name = Column(String(100), nullable=False, unique=True)
    CredType = Column(String(50), nullable=False)
    SecretData = Column(Text, nullable=True)
    IsActive = Column(Boolean, default=True, server_default=true())

    __mapper_args__ = {
        'polymorphic_identity': 'CREDENTIAL',
    }


class Tag(MasterObject):
    """
    A label any master object can carry. A tag's variables act as if they were on
    what carries it, and a tag can sit under a parent, nested to any depth,
    inheriting its parent's variables. Names are unique under one parent, so a tag
    is named by its path: Environment/TEST (see engine/tag_vars.py).
    """
    __tablename__ = 'Tags'
    __table_args__ = (
        UniqueConstraint('Parent_MasterObject_id', 'Name', name='uq_tag_parent_name'),
    )

    # No full stop or slash: a tag is named as ${TAG:Parent/Child.Variable}
    NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), primary_key=True)
    # A tag with children cannot be deleted, so the database refuses it too
    Parent_MasterObject_id = Column(Integer, ForeignKey('Tags.MasterObject_id', ondelete='RESTRICT'), nullable=True)
    Name = Column(String(100), nullable=False)
    Description = Column(Text, nullable=True)

    parent = relationship("Tag", remote_side=[MasterObject_id], foreign_keys=[Parent_MasterObject_id],
                          backref="children")

    __mapper_args__ = {
        'polymorphic_identity': 'TAG',
        'inherit_condition': MasterObject_id == MasterObject.id,
    }


class Scheduler(MasterObject):
    """
    A workload automation product that runs AutoApp jobs: one installation of
    RunMyJobs, Control-M, ActiveBatch and so on. AutoApp can serve several at once;
    the runner's --scheduler names the one starting a run. ApiUrl is where AutoApp
    reaches it, to read its jobs' parameters; the credential for that is a secret
    variable on the scheduler.
    """
    __tablename__ = 'Schedulers'

    TECHNOLOGIES = ("RUNMYJOBS", "ACTIVEBATCH", "CONTROL_M", "TIDAL", "CRON", "STANDIN", "OTHER")

    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), primary_key=True)
    Name = Column(String(100), nullable=False, unique=True)
    Technology = Column(String(20), nullable=False, default='OTHER', server_default='OTHER')
    ApiUrl = Column(String(512), nullable=True)
    Description = Column(Text, nullable=True)
    IsActive = Column(Boolean, default=True, server_default=true())

    __mapper_args__ = {
        'polymorphic_identity': 'SCHEDULER',
    }


class Job(MasterObject):
    """
    Anything that runs. JobType says what it is made of: STEPS (its JobSteps) or WORKFLOW
    (other jobs, its WorkflowItems, with prerequisites between them; docs/WORKFLOWS.md).
    What all jobs share lives here; what belongs to one type lives in that type's tables.
    """
    __tablename__ = 'Jobs'

    # JobKey doubles as the name of the job's working folder, so it must be a safe folder name
    JOB_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    TYPES = ("STEPS", "WORKFLOW")

    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), primary_key=True)
    # The job's unique name: stable, environment-independent, and what the WLA scheduler passes to the runner
    JobKey = Column(String(320), nullable=False, unique=True)
    Description = Column(Text, nullable=True)
    IsActive = Column(Boolean, default=True, server_default=true())
    JobType = Column(String(20), nullable=False, default="STEPS", server_default="STEPS")
    # The workflow an embedded job belongs to (docs/WORKFLOWS.md); empty for a job of its own
    Owner_MasterObject_id = Column(Integer, ForeignKey('Jobs.MasterObject_id', ondelete='CASCADE'), nullable=True)
    # The return codes that mean the job succeeded, e.g. "0", "0, 4" or "0-4"; empty means 0
    SuccessReturnCodes = Column(String(100), nullable=True)
    # A workflow's completion rules (docs/WORKFLOWS_PHASE4.md): when it succeeds, as a condition over
    # its jobs (empty: the default, unless a failure went unhandled); and whose return code it ends
    # with, by the job's name in it (empty: 0 if it succeeded, 1 if not)
    SucceedsWhen = Column(Text, nullable=True)
    ReturnCodeFrom = Column(String(100), nullable=True)

    @validates("JobKey")
    def _validate_job_key(self, _attribute, value):
        if not value or not self.JOB_KEY_PATTERN.match(value):
            raise ValueError(
                f"Invalid JobKey '{value}': use letters, digits, '-', '_' and '.', starting with a letter or digit."
            )
        return value

    steps = relationship("JobStep", backref="job", cascade="all, delete-orphan", passive_deletes=True)
    reactions = relationship("Reaction", foreign_keys="Reaction.Job_MasterObject_id", cascade="all, delete-orphan",
                             passive_deletes=True, order_by=lambda: [Reaction.Section, Reaction.ReactionOrder])
    # A workflow's items, in outline order
    items = relationship("WorkflowItem", foreign_keys="WorkflowItem.Workflow_MasterObject_id", backref="workflow",
                         cascade="all, delete-orphan", passive_deletes=True, order_by="WorkflowItem.ItemOrder")

    __mapper_args__ = {
        'polymorphic_identity': 'JOB',
        'inherit_condition': MasterObject_id == MasterObject.id,
    }


# ============================================================================
# Universal Metadata & Variable Entities
# ============================================================================
class Variable(Base):
    __tablename__ = 'Variables'
    __table_args__ = (
        UniqueConstraint('MasterObject_id', 'VarName', name='uq_obj_var'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), nullable=False)
    VarName = Column(String(100), nullable=False)
    VarValue = Column(Text, nullable=True)
    IsSecret = Column(Boolean, default=False, server_default=false())
    Description = Column(Text, nullable=True)


class TagAssignment(Base):
    __tablename__ = 'TagAssignments'
    __table_args__ = (
        UniqueConstraint('Tag_MasterObject_id', 'Target_MasterObject_id', name='uq_tag_target'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # A tag still attached to something cannot be deleted
    Tag_MasterObject_id = Column(Integer, ForeignKey('Tags.MasterObject_id', ondelete='RESTRICT'), nullable=False)
    Target_MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), nullable=False)

    tag = relationship("Tag", foreign_keys=[Tag_MasterObject_id])


class SettingValue(Base):
    """
    A system-wide setting changed from its default. The settings themselves, their
    defaults and what they mean, are declared in engine/settings.py.
    """
    __tablename__ = 'Settings'

    SettingKey = Column(String(100), primary_key=True)
    SettingValue = Column(Text, nullable=False)
    UpdatedDateTime = Column(DateTime, default=utcnow, onupdate=utcnow)
    UpdatedBy = Column(String(100), nullable=True)


# ============================================================================
# Unified Endpoint Model
# ============================================================================
class Endpoint(MasterObject):
    """
    A registered place files come from or go to. Like the other definitions it is a
    master object: it has a created and changed date, and can hold variables and tags.
    Its id (endpoint.id) is its MasterObjects id, which is also MasterObject_id.
    """
    __tablename__ = 'Endpoints'

    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), primary_key=True)
    # Stable name that job steps use to reference this endpoint (SourceEndpoint / DestEndpoint)
    Name = Column(String(100), nullable=False, unique=True)
    Site_MasterObject_id = Column(Integer, ForeignKey('Sites.MasterObject_id', ondelete='SET NULL'), nullable=True)
    Application_MasterObject_id = Column(Integer, ForeignKey('Applications.MasterObject_id', ondelete='SET NULL'), nullable=True)
    Path = Column(String(256), nullable=False)
    FilenamePattern = Column(String(128), nullable=False)
    Description = Column(String(256), nullable=True)

    # foreign_keys spelled out: an endpoint's table refers to three master objects (itself, its site, its application)
    site = relationship("Site", foreign_keys=[Site_MasterObject_id])
    application = relationship("Application", foreign_keys=[Application_MasterObject_id])

    __mapper_args__ = {
        'polymorphic_identity': 'ENDPOINT',
        'inherit_condition': MasterObject_id == MasterObject.id,
    }


# ============================================================================
# Step Catalog & Job Setup
# ============================================================================
class StepType(Base):
    __tablename__ = 'StepTypes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    TypeName = Column("Name", String(100), nullable=False)
    HandlerClass = Column("Code", String(50), nullable=False, unique=True)
    Description = Column(Text, nullable=True)
    IsActive = Column(Boolean, default=True, server_default=true())

    definitions = relationship("StepDefinition", backref="step_type", order_by="StepDefinition.DisplayOrder",
                               cascade="all, delete-orphan", passive_deletes=True)


class StepDefinition(Base):
    __tablename__ = 'StepDefinitions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    StepType_id = Column(Integer, ForeignKey('StepTypes.id', ondelete='CASCADE'), nullable=False)
    ParamName = Column("ParameterName", String(100), nullable=False) # <--- Python attribute is ParamName
    # STRING, TEXT, BOOLEAN, INTEGER, CHOICE or LOCATION (see engine/step_catalog.py)
    DataType = Column(String(20), default='STRING', server_default='STRING')
    IsRequired = Column(Boolean, default=True, server_default=true())
    DefaultValue = Column(Text, nullable=True)
    Description = Column(Text, nullable=True)
    # Position of the parameter in the job editor's form
    DisplayOrder = Column(Integer, nullable=False, default=0, server_default=text('0'))
    # For a LOCATION: SOURCE (files are read from it) or DEST (files are written to it)
    LocationRole = Column(String(10), nullable=True)
    # For a CHOICE: the allowed values, as a JSON list
    AllowedValues = Column(Text, nullable=True)


class JobStep(Base):
    """
    One step of a job. Steps form a tree (see docs/FLOW_CONTROL.md): a step inside a block
    step (If, For Each File, While, and an If's Then, ElseIf and Else) points at it with
    ParentStep_id, and StepOrder is its position among that block's steps.
    """
    __tablename__ = 'JobSteps'

    # How other steps refer to this one, as %{StepName.Status}
    NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
    # What happens to the job when the step fails
    ON_FAILURE = ("FAIL_JOB", "CONTINUE", "END_SUCCESS")

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column("Job_MasterObject_id", Integer, ForeignKey('Jobs.MasterObject_id', ondelete='CASCADE'), nullable=False)
    StepType_id = Column(Integer, ForeignKey('StepTypes.id'), nullable=False)
    # The block step this one sits in; NULL at the top level of the job
    ParentStep_id = Column(Integer, ForeignKey('JobSteps.id', ondelete='CASCADE'), nullable=True)
    StepOrder = Column(Integer, default=1, server_default=text('1'))
    Title = Column("StepTitle", String(150), nullable=True, default="Execution Step", server_default="Execution Step")
    StepName = Column(String(64), nullable=True)
    IsActive = Column(Boolean, default=True, server_default=true())
    OnFailure = Column(String(20), nullable=False, default="FAIL_JOB", server_default="FAIL_JOB")

    step_type = relationship("StepType")
    parameters = relationship("JobStepParameter", backref="job_step", cascade="all, delete-orphan", passive_deletes=True)
    # Through this relationship, a block's steps are deleted before the block itself
    children = relationship("JobStep", backref=backref("parent", remote_side=[id]), order_by="JobStep.StepOrder")


class JobStepParameter(Base):
    __tablename__ = 'JobStepParameters'

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_step_id = Column("JobStep_id", Integer, ForeignKey('JobSteps.id', ondelete='CASCADE'), nullable=False)
    ParamName = Column("ParameterName", String(100), nullable=False) # <--- Python attribute is ParamName
    ParamValue = Column("ParameterValue", Text, nullable=True)     # <--- Python attribute is ParamValue


# ============================================================================
# Workflows: the jobs a workflow uses, and the prerequisites between them
# ============================================================================
class WorkflowItem(Base):
    """
    One job a workflow uses, under a name of its own in that workflow, so the same job can
    be used more than once. Conditions refer to it by that name (%{Name.Status}), so the
    name holds no dots or spaces. With the join CUSTOM, StartRule is a condition over the jobs it
    names (docs/WORKFLOWS_PHASE4.md); they are its prerequisites, with the test RULE.
    """
    __tablename__ = 'WorkflowItems'
    __table_args__ = (UniqueConstraint('Workflow_MasterObject_id', 'ItemName', name='uq_workflow_item_name'),)

    NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    JOIN_RULES = ("ALL", "ANY", "CUSTOM")
    DISABLED_HERE = ("STOP", "PASS_THROUGH")

    id = Column(Integer, primary_key=True, autoincrement=True)
    Workflow_MasterObject_id = Column(Integer, ForeignKey('Jobs.MasterObject_id', ondelete='CASCADE'), nullable=False, index=True)
    ItemName = Column(String(100), nullable=False)
    # The job it runs; a job used by a workflow cannot be deleted
    Job_MasterObject_id = Column(Integer, ForeignKey('Jobs.MasterObject_id', ondelete='RESTRICT'), nullable=False)
    # ALL: it starts when all its prerequisites hold; ANY: when any one does; CUSTOM: when StartRule does
    JoinRule = Column(String(10), nullable=False, default="ALL", server_default="ALL")
    StartRule = Column(Text, nullable=True)
    ItemOrder = Column(Integer, nullable=False, default=1, server_default=text('1'))
    # Disable here (docs/WORKFLOWS.md): empty, STOP (it ends Disabled) or PASS_THROUGH (it ends Bypassed)
    DisabledHere = Column(String(20), nullable=True)
    # True: this use's own Reactions replace its job's, even when it has none
    ReactionsOverridden = Column(Boolean, nullable=False, default=False, server_default=false())

    job = relationship("Job", foreign_keys=[Job_MasterObject_id])
    reactions = relationship("Reaction", foreign_keys="Reaction.Item_id", cascade="all, delete-orphan",
                             passive_deletes=True, order_by=lambda: [Reaction.Section, Reaction.ReactionOrder])
    prerequisites = relationship("WorkflowPrerequisite", foreign_keys="WorkflowPrerequisite.Item_id", backref="item",
                                 cascade="all, delete-orphan", passive_deletes=True, order_by="WorkflowPrerequisite.id")
    # This use's own variables, over the job's own (the This use level of the Variable precedence setting)
    variables = relationship("WorkflowItemVariable", cascade="all, delete-orphan", passive_deletes=True,
                             order_by="WorkflowItemVariable.VarName")


class WorkflowItemVariable(Base):
    """A variable of one use of a job in a workflow, overriding the job's own for that use only."""
    __tablename__ = 'WorkflowItemVariables'
    __table_args__ = (UniqueConstraint('Item_id', 'VarName', name='uq_item_var'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    Item_id = Column(Integer, ForeignKey('WorkflowItems.id', ondelete='CASCADE'), nullable=False, index=True)
    VarName = Column(String(100), nullable=False)
    VarValue = Column(Text, nullable=True)
    IsSecret = Column(Boolean, default=False, server_default=false())
    Description = Column(Text, nullable=True)


class WorkflowPrerequisite(Base):
    """
    What a workflow's item waits for before it starts: another of the workflow's items, and
    how that one must have ended. Test is SUCCESS, FAILED, ENDED (any final status), RC
    (one of ReturnCodes, e.g. "0-4") or RULE (named in the item's Custom rule, which decides).
    Condition is unused: a Custom rule is on the item, as StartRule.
    """
    __tablename__ = 'WorkflowPrerequisites'

    TESTS = ("SUCCESS", "FAILED", "ENDED", "RC")
    RULE = "RULE"

    id = Column(Integer, primary_key=True, autoincrement=True)
    Item_id = Column(Integer, ForeignKey('WorkflowItems.id', ondelete='CASCADE'), nullable=False, index=True)
    TargetItem_id = Column(Integer, ForeignKey('WorkflowItems.id', ondelete='CASCADE'), nullable=True)
    Test = Column(String(20), nullable=False, default="SUCCESS", server_default="SUCCESS")
    ReturnCodes = Column(String(100), nullable=True)
    Condition = Column(Text, nullable=True)

    target = relationship("WorkflowItem", foreign_keys=[TargetItem_id])


class Reaction(Base):
    """
    What happens after a job ends, chosen by how it ended (docs/WORKFLOWS_PHASE3.md). It belongs
    to a job (Job_MasterObject_id), or to one use of a job in a workflow (Item_id), whose list
    then replaces the job's. Section NEXT: in order, the first that holds decides what happens
    next; ALSO: every one that holds fires. The When is a test as a prerequisite's is: SUCCESS,
    FAILED, ENDED or RC (one of WhenReturnCodes). WhenCondition is for conditions written in SQL (later).
    """
    __tablename__ = 'Reactions'
    __table_args__ = (
        CheckConstraint('(Job_MasterObject_id IS NULL) <> (Item_id IS NULL)', name='ck_reaction_one_owner'),
    )

    SECTIONS = ("NEXT", "ALSO")
    TESTS = ("SUCCESS", "FAILED", "ENDED", "RC")

    id = Column(Integer, primary_key=True, autoincrement=True)
    Job_MasterObject_id = Column(Integer, ForeignKey('Jobs.MasterObject_id', ondelete='CASCADE'), nullable=True, index=True)
    Item_id = Column(Integer, ForeignKey('WorkflowItems.id', ondelete='CASCADE'), nullable=True, index=True)
    Section = Column(String(10), nullable=False, default="NEXT", server_default="NEXT")
    ReactionOrder = Column(Integer, nullable=False, default=1, server_default=text('1'))
    WhenTest = Column(String(20), nullable=False, default="FAILED", server_default="FAILED")
    WhenReturnCodes = Column(String(100), nullable=True)
    WhenCondition = Column(Text, nullable=True)

    actions = relationship("ReactionAction", backref="reaction", cascade="all, delete-orphan",
                           passive_deletes=True, order_by="ReactionAction.ActionOrder")


class ReactionAction(Base):
    """
    One thing a Reaction does. Decisions change what happens next: COUNT_AS_SUCCEEDED,
    COUNT_AS_FAILED, RERUN (this job, after WaitSeconds, at most MaxTimes), RERUN_FROM (TargetItem
    and everything between it and this job, at most MaxTimes), SKIP (TargetItem), SKIP_BRANCH (what
    waits for this job), KILL_WORKFLOW. A side effect changes nothing in the run: START_WORKFLOW
    (TargetJob). RERUN_FROM, SKIP, SKIP_BRANCH and KILL_WORKFLOW only make sense on a use.
    """
    __tablename__ = 'ReactionActions'

    DECISIONS = ("COUNT_AS_SUCCEEDED", "COUNT_AS_FAILED", "RERUN", "RERUN_FROM", "SKIP", "SKIP_BRANCH", "KILL_WORKFLOW")
    SIDE_EFFECTS = ("START_WORKFLOW",)
    ONLY_IN_WORKFLOWS = ("RERUN_FROM", "SKIP", "SKIP_BRANCH", "KILL_WORKFLOW")

    id = Column(Integer, primary_key=True, autoincrement=True)
    Reaction_id = Column(Integer, ForeignKey('Reactions.id', ondelete='CASCADE'), nullable=False, index=True)
    ActionOrder = Column(Integer, nullable=False, default=1, server_default=text('1'))
    Action = Column(String(30), nullable=False)
    MaxTimes = Column(Integer, nullable=True)
    WaitSeconds = Column(Integer, nullable=True)
    TargetItem_id = Column(Integer, ForeignKey('WorkflowItems.id', ondelete='CASCADE'), nullable=True)
    # The workflow START_WORKFLOW starts; a workflow named here cannot be deleted
    TargetJob_MasterObject_id = Column(Integer, ForeignKey('Jobs.MasterObject_id', ondelete='RESTRICT'), nullable=True)

    target_item = relationship("WorkflowItem", foreign_keys=[TargetItem_id])
    target_job = relationship("Job", foreign_keys=[TargetJob_MasterObject_id])


# ============================================================================
# Run History, File Operations & Change Audits
# ============================================================================
class JobRun(Base):
    """One execution of a job by the runner. The scheduler stays the authority on scheduling;
    this is AutoApp's side of the run, and what each file operation points back to."""
    __tablename__ = 'JobRuns'

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Generated by the runner each time it starts, so every execution is distinct
    RunID = Column(String(36), nullable=False, unique=True)
    # Kept as text as well as a link, so history survives the job being deleted
    JobKey = Column(String(320), nullable=False, index=True)
    Job_MasterObject_id = Column(Integer, ForeignKey('Jobs.MasterObject_id', ondelete='SET NULL'), nullable=True)
    # What the scheduler passed: its instance ID, and a run/restart count where it reuses the ID
    SchedulerInstanceID = Column(String(64), nullable=False, index=True)
    RunNumber = Column(Integer, nullable=False, default=1, server_default=text('1'))
    SchedulerName = Column(String(100), nullable=True)
    # The date the run is for, where the scheduler gave one (Control-M's order date)
    BusinessDate = Column(Date, nullable=True)
    Host = Column(String(255), nullable=True)
    Status = Column(String(20), nullable=False, default='RUNNING', server_default='RUNNING')
    ErrorMessage = Column(Text, nullable=True)
    StartedDateTime = Column(PreciseDateTime, nullable=True)
    EndedDateTime = Column(PreciseDateTime, nullable=True)
    # What the job's steps reported (0 unless a step set one), and why it ended as it did: see docs/WORKFLOWS.md
    ReturnCode = Column(Integer, nullable=True)
    Reason = Column(String(40), nullable=True)
    JobType = Column(String(20), nullable=False, default="STEPS", server_default="STEPS")
    # A job run inside a workflow run: that run, the job's path in the workflow ("Transform/Stage"),
    # and which attempt this is
    ParentRun_id = Column(Integer, ForeignKey('JobRuns.id', ondelete='SET NULL'), nullable=True, index=True)
    WorkflowPath = Column(String(1000), nullable=True)
    Attempt = Column(Integer, nullable=False, default=1, server_default=text('1'))
    # Set when someone asks a workflow run to start nothing more
    CancelRequestedDateTime = Column(PreciseDateTime, nullable=True)
    # Set when someone asks a running workflow to kill what runs and cancel the rest
    KillRequestedDateTime = Column(PreciseDateTime, nullable=True)
    # The runner's process on Host, so a running job can be killed
    ProcessID = Column(Integer, nullable=True)
    # Where a Reaction counted the run as succeeded or failed: what it ended as on its own
    StatusBeforeOverride = Column(String(20), nullable=True)
    # The files the job delivered (written to a destination) and their size, which it reports itself
    # with its end, never counted from its operations; a workflow's are its jobs' added up
    FileCount = Column(Integer, nullable=True)
    Bytes = Column(BigInteger, nullable=True)
    # The job log is a file on the host that ran the job (engine/log_files.py): where it is within that
    # host's log folder, and when it was removed for being older than the Settings page's limit
    LogFile = Column(String(500), nullable=True)
    LogRemovedDateTime = Column(PreciseDateTime, nullable=True)
    # A workflow run's variables, fixed as it starts (engine/workflow_vars.py): its own and its tags',
    # and each use's, as JSON. A secret is kept by name only, never its value
    WorkflowVariables = Column(Text, nullable=True)

    job = relationship("Job")
    operations = relationship("Operation", back_populates="run", cascade="all, delete-orphan",
                              passive_deletes=True, order_by="Operation.Seq")


class WorkflowRunItem(Base):
    """
    One item of a workflow run, and where it stands: PENDING (not started), WAITING,
    RUNNING, SUCCESS, FAILED or NOT_RUN, with the Reason. An item that never started has
    no job run of its own, so this is where the run says so.
    """
    __tablename__ = 'WorkflowRunItems'
    __table_args__ = (UniqueConstraint('WorkflowRun_id', 'Path', name='uq_workflow_run_item_path'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    WorkflowRun_id = Column(Integer, ForeignKey('JobRuns.id', ondelete='CASCADE'), nullable=False, index=True)
    Item_id = Column(Integer, ForeignKey('WorkflowItems.id', ondelete='SET NULL'), nullable=True)
    Path = Column(String(1000), nullable=False)
    ItemName = Column(String(100), nullable=False)
    JobKey = Column(String(320), nullable=False)
    ItemOrder = Column(Integer, nullable=False, default=1, server_default=text('1'))
    Status = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    Reason = Column(String(40), nullable=True)
    ReturnCode = Column(Integer, nullable=True)
    StatusBeforeOverride = Column(String(20), nullable=True)
    # The runner of its latest attempt, recorded by the workflow runner as it starts it, so Kill
    # never waits for the job's own records to arrive
    ProcessID = Column(Integer, nullable=True)
    # The job run of its latest attempt
    ChildRun_id = Column(Integer, ForeignKey('JobRuns.id', ondelete='SET NULL'), nullable=True)
    Attempt = Column(Integer, nullable=False, default=0, server_default=text('0'))
    StartedDateTime = Column(PreciseDateTime, nullable=True)
    EndedDateTime = Column(PreciseDateTime, nullable=True)

    child_run = relationship("JobRun", foreign_keys=[ChildRun_id])


class ReactionEvent(Base):
    """
    A Reaction's action that fired after a job ended, or would have but had reached its limit
    (Result TOOK_EFFECT or LIMIT_REACHED). The record behind "at most N times", counted within
    a workflow run, and what the run view and the job log show. JobRun is the attempt it was
    judged on; Action and Message are kept as text, so they survive the Reaction being edited.
    """
    __tablename__ = 'ReactionEvents'

    id = Column(Integer, primary_key=True, autoincrement=True)
    JobRun_id = Column(Integer, ForeignKey('JobRuns.id', ondelete='CASCADE'), nullable=False, index=True)
    WorkflowRun_id = Column(Integer, ForeignKey('JobRuns.id', ondelete='CASCADE'), nullable=True, index=True)
    WorkflowPath = Column(String(1000), nullable=True)
    ReactionAction_id = Column(Integer, ForeignKey('ReactionActions.id', ondelete='SET NULL'), nullable=True)
    Action = Column(String(30), nullable=False)
    Result = Column(String(20), nullable=False, default="TOOK_EFFECT", server_default="TOOK_EFFECT")
    Message = Column(Text, nullable=True)
    EventDateTime = Column(PreciseDateTime, nullable=False, default=lambda: utcnow())



class ConditionCheck(Base):
    """
    A workflow condition worked out in a run, when it decided something (docs/WORKFLOWS_PHASE4.md):
    a job's Custom rule (Kind START_RULE, Path the job's) or the workflow's Succeeds when
    (SUCCEEDS_WHEN, no Path). The text and the values it used are kept as they were, so Explain
    can show each part of a past run's condition, held or not. Result: TRUE, FALSE or UNKNOWN.
    """
    __tablename__ = 'ConditionChecks'

    KINDS = ("START_RULE", "SUCCEEDS_WHEN")

    id = Column(Integer, primary_key=True, autoincrement=True)
    WorkflowRun_id = Column(Integer, ForeignKey('JobRuns.id', ondelete='CASCADE'), nullable=False, index=True)
    Path = Column(String(1000), nullable=True)
    Kind = Column(String(20), nullable=False)
    ConditionText = Column(Text, nullable=False)
    # {"%{Extract.Status}": "SUCCESS", ...}, as JSON
    ValuesJson = Column(Text, nullable=False)
    Result = Column(String(10), nullable=False)
    CheckedDateTime = Column(PreciseDateTime, nullable=False, default=lambda: utcnow())
class Operation(Base):
    """
    One thing a step did. For a file step that is one file: where it came from, where it
    went, and how big it was at each end. A step that handles no files (a SQL statement, a
    REST call) leaves the file columns empty and describes what it did in Details.
    """
    __tablename__ = 'Operations'
    __table_args__ = (
        # Seq is the record's position in the run's spool; it makes loading the same spool twice harmless
        UniqueConstraint('JobRun_id', 'Seq', name='uq_run_seq'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    JobRun_id = Column(Integer, ForeignKey('JobRuns.id', ondelete='CASCADE'), nullable=False, index=True)
    Seq = Column(Integer, nullable=False)
    JobStep_id = Column(Integer, ForeignKey('JobSteps.id', ondelete='SET NULL'), nullable=True)
    # The position of the step's top-level step: 3 for step 3.1
    StepOrder = Column(Integer, nullable=True)
    # The step's number, e.g. 3.1 inside step 3, and which pass of the loops around it: 2, or 2.3 in nested loops
    StepNumber = Column(String(50), nullable=True)
    Iteration = Column(String(50), nullable=True)
    OpType = Column(String(50), nullable=False)
    OpStatus = Column(String(20), nullable=False)
    # Registered Endpoints the file came from / went to; NULL for a location inside the working folder
    SourceEndpoint_id = Column(Integer, ForeignKey('Endpoints.MasterObject_id', ondelete='SET NULL'), nullable=True)
    SourcePath = Column(Text, nullable=True)
    SourceFilename = Column(String(255), nullable=True, index=True)
    SourceSize = Column(BigInteger, nullable=True)
    DestEndpoint_id = Column(Integer, ForeignKey('Endpoints.MasterObject_id', ondelete='SET NULL'), nullable=True)
    DestPath = Column(Text, nullable=True)
    DestFilename = Column(String(255), nullable=True, index=True)
    DestSize = Column(BigInteger, nullable=True)
    # SHA-256 of the file, recorded only when the step asks for it (Checksum=True)
    Checksum = Column(String(64), nullable=True)
    # Anything else worth keeping about the operation, as JSON; the whole record for a step with no files
    Details = Column(Text, nullable=True)
    ErrorMessage = Column(Text, nullable=True)
    StartedDateTime = Column(PreciseDateTime, nullable=True)
    EndedDateTime = Column(PreciseDateTime, nullable=True)

    run = relationship("JobRun", back_populates="operations")
    source_endpoint = relationship("Endpoint", foreign_keys=[SourceEndpoint_id])
    dest_endpoint = relationship("Endpoint", foreign_keys=[DestEndpoint_id])


class Audit(Base):
    """A change to a definition (job, endpoint, variable, ...): who did what, and when."""
    __tablename__ = 'Audits'

    id = Column(Integer, primary_key=True, autoincrement=True)
    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='SET NULL'), nullable=True)
    Action = Column(String(50), nullable=False)
    PerformedBy = Column(String(100), default='system', server_default='system')
    Details = Column(Text, nullable=True)
    CreatedDateTime = Column(DateTime, default=utcnow, server_default=func.now())


# ============================================================================
# Text comparison
# ============================================================================
# Names, paths and filenames are case-sensitive: 'DEV-LOAD' and 'dev-load' are two jobs, and
# 'Report.csv' and 'report.csv' two files. SQLite and PostgreSQL compare text that way already.
# MariaDB and MySQL ignore case unless a table says otherwise, so every table says otherwise.
# (Searches that should ignore case, such as the operations log, lower-case both sides themselves.)
for _table in Base.metadata.tables.values():
    for _dialect in ("mysql", "mariadb"):
        _table.dialect_options[_dialect]["engine"] = "InnoDB"
        _table.dialect_options[_dialect]["charset"] = "utf8mb4"
        _table.dialect_options[_dialect]["collate"] = "utf8mb4_bin"


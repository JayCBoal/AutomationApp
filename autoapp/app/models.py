import datetime
import re
from sqlalchemy import (
    BigInteger, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum, UniqueConstraint,
    false, func, text, true
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import declarative_base, relationship, validates

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
        Enum('APPLICATION', 'ENTITY', 'SITE', 'CREDENTIAL', 'TAG', 'JOB', 'ENDPOINT', name='object_type_enum'),
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


class Job(MasterObject):
    __tablename__ = 'Jobs'

    # JobKey doubles as the name of the job's working folder, so it must be a safe folder name
    JOB_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), primary_key=True)
    # The job's unique name: stable, environment-independent, and what the WLA scheduler passes to the runner
    JobKey = Column(String(320), nullable=False, unique=True)
    Description = Column(Text, nullable=True)
    IsActive = Column(Boolean, default=True, server_default=true())

    @validates("JobKey")
    def _validate_job_key(self, _attribute, value):
        if not value or not self.JOB_KEY_PATTERN.match(value):
            raise ValueError(
                f"Invalid JobKey '{value}': use letters, digits, '-', '_' and '.', starting with a letter or digit."
            )
        return value

    steps = relationship("JobStep", backref="job", cascade="all, delete-orphan", passive_deletes=True)

    __mapper_args__ = {
        'polymorphic_identity': 'JOB',
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
    __tablename__ = 'JobSteps'

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column("Job_MasterObject_id", Integer, ForeignKey('Jobs.MasterObject_id', ondelete='CASCADE'), nullable=False)
    StepType_id = Column(Integer, ForeignKey('StepTypes.id'), nullable=False)
    StepOrder = Column(Integer, default=1, server_default=text('1'))
    Title = Column("StepTitle", String(150), nullable=True, default="Execution Step", server_default="Execution Step")
    IsActive = Column(Boolean, default=True, server_default=true())

    step_type = relationship("StepType")
    parameters = relationship("JobStepParameter", backref="job_step", cascade="all, delete-orphan", passive_deletes=True)


class JobStepParameter(Base):
    __tablename__ = 'JobStepParameters'

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_step_id = Column("JobStep_id", Integer, ForeignKey('JobSteps.id', ondelete='CASCADE'), nullable=False)
    ParamName = Column("ParameterName", String(100), nullable=False) # <--- Python attribute is ParamName
    ParamValue = Column("ParameterValue", Text, nullable=True)     # <--- Python attribute is ParamValue


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
    Host = Column(String(255), nullable=True)
    Status = Column(String(20), nullable=False, default='RUNNING', server_default='RUNNING')
    ErrorMessage = Column(Text, nullable=True)
    StartedDateTime = Column(PreciseDateTime, nullable=True)
    EndedDateTime = Column(PreciseDateTime, nullable=True)

    job = relationship("Job")
    operations = relationship("Operation", back_populates="run", cascade="all, delete-orphan",
                              passive_deletes=True, order_by="Operation.Seq")


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
    StepOrder = Column(Integer, nullable=True)
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

import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# ============================================================================
# MasterObject Polymorphic Base Model
# ============================================================================
class MasterObject(Base):
    __tablename__ = 'MasterObjects'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ObjectType = Column(
        Enum('APPLICATION', 'ENTITY', 'SITE', 'CREDENTIAL', 'TAG', 'PROCESS', 'JOB', name='object_type_enum'),
        nullable=False
    )
    CreatedDateTime = Column(DateTime, default=datetime.datetime.utcnow)
    CreatedBy = Column(String(100), default='system')
    ModifiedDateTime = Column(DateTime, onupdate=datetime.datetime.utcnow)
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
    IsActive = Column(Boolean, default=True)

    __mapper_args__ = {
        'polymorphic_identity': 'APPLICATION',
    }


class Entity(MasterObject):
    __tablename__ = "Entities"

    MasterObject_id = Column(Integer, ForeignKey("MasterObjects.id", ondelete="CASCADE"), primary_key=True)
    Name = Column(String(64), nullable=False, unique=True)
    Abbr = Column(String(10), nullable=False)
    Description = Column(String(256), nullable=True)

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
    Port = Column(Integer, default=22)
    Protocol = Column(String(16), default="SFTP")
    Description = Column(String(256), nullable=True)

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
    IsActive = Column(Boolean, default=True)

    __mapper_args__ = {
        'polymorphic_identity': 'CREDENTIAL',
    }


class Tag(MasterObject):
    __tablename__ = 'Tags'

    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), primary_key=True)
    TagName = Column(String(100), nullable=False, unique=True)
    Category = Column(String(50), nullable=True)
    Description = Column(Text, nullable=True)

    __mapper_args__ = {
        'polymorphic_identity': 'TAG',
    }


class Process(MasterObject):
    __tablename__ = 'Processes'

    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), primary_key=True)
    Name = Column(String(150), nullable=False, unique=True)
    Description = Column(Text, nullable=True)
    IsActive = Column(Boolean, default=True)

    # Disambiguate relationship by explicitly defining foreign_keys
    jobs = relationship(
        "Job",
        foreign_keys="[Job.process_id]",
        backref="process",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    __mapper_args__ = {
        'polymorphic_identity': 'PROCESS',
    }


class Job(MasterObject):
    __tablename__ = 'Jobs'

    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), primary_key=True)
    process_id = Column(
        "Process_MasterObject_id",
        Integer,
        ForeignKey('Processes.MasterObject_id', ondelete='CASCADE'),
        nullable=False
    )
    Name = Column(String(150), nullable=False)
    Description = Column(Text, nullable=True)
    ExecutionOrder = Column(Integer, default=1)
    IsActive = Column(Boolean, default=True)

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
    IsSecret = Column(Boolean, default=False)
    Description = Column(Text, nullable=True)


class TagAssignment(Base):
    __tablename__ = 'TagAssignments'
    __table_args__ = (
        UniqueConstraint('Tag_MasterObject_id', 'Target_MasterObject_id', name='uq_tag_target'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    Tag_MasterObject_id = Column(Integer, ForeignKey('Tags.MasterObject_id', ondelete='CASCADE'), nullable=False)
    Target_MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), nullable=False)


# ============================================================================
# Unified Endpoint Model
# ============================================================================
class Endpoint(Base):
    __tablename__ = 'Endpoints'

    id = Column(Integer, primary_key=True, autoincrement=True)
    EndpointType = Column(Enum('SOURCE', 'DELIVERY', name='endpoint_type_enum'), nullable=False)
    Site_MasterObject_id = Column(Integer, ForeignKey('Sites.MasterObject_id', ondelete='SET NULL'), nullable=True)
    Application_MasterObject_id = Column(Integer, ForeignKey('Applications.MasterObject_id', ondelete='SET NULL'), nullable=True)
    Path = Column(String(256), nullable=False)
    FilenamePattern = Column(String(128), nullable=False)
    Description = Column(String(256), nullable=True)
    ModifiedDateTime = Column(DateTime, onupdate=datetime.datetime.utcnow)
    ModifiedBy = Column(String(50), nullable=True)

    site = relationship("Site")
    application = relationship("Application")


# ============================================================================
# Step Catalog & Job Setup
# ============================================================================
class StepType(Base):
    __tablename__ = 'StepTypes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    TypeName = Column("Name", String(100), nullable=False)
    HandlerClass = Column("Code", String(50), nullable=False, unique=True)
    Description = Column(Text, nullable=True)
    IsActive = Column(Boolean, default=True)

    definitions = relationship("StepDefinition", backref="step_type")


class StepDefinition(Base):
    __tablename__ = 'StepDefinitions'
    __table_args__ = (
        UniqueConstraint('StepType_id', 'ParameterName', name='uq_steptype_param'), # <-- Match ParameterName
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    StepType_id = Column(Integer, ForeignKey('StepTypes.id', ondelete='CASCADE'), nullable=False)
    ParamName = Column("ParameterName", String(100), nullable=False)
    DataType = Column(String(20), default='STRING')
    IsRequired = Column(Boolean, default=True)
    DefaultValue = Column(Text, nullable=True)
    Description = Column(Text, nullable=True)


class JobStep(Base):
    __tablename__ = 'JobSteps'

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column("Job_MasterObject_id", Integer, ForeignKey('Jobs.MasterObject_id', ondelete='CASCADE'), nullable=False)
    StepType_id = Column(Integer, ForeignKey('StepTypes.id'), nullable=False)
    StepOrder = Column(Integer, default=1)
    Title = Column("StepTitle", String(150), nullable=True, default="Execution Step")
    IsActive = Column(Boolean, default=True)

    step_type = relationship("StepType")
    parameters = relationship("JobStepParameter", backref="job_step", cascade="all, delete-orphan", passive_deletes=True)


class JobStepParameter(Base):
    __tablename__ = 'JobStepParameters'
    __table_args__ = (
        UniqueConstraint('JobStep_id', 'ParameterName', name='uq_jobstep_param'), # <-- Match ParameterName
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_step_id = Column("JobStep_id", Integer, ForeignKey('JobSteps.id', ondelete='CASCADE'), nullable=False)
    ParamName = Column("ParameterName", String(100), nullable=False)
    ParamValue = Column("ParameterValue", Text, nullable=True)


# ============================================================================
# Operational Telemetry & Execution Audits
# ============================================================================
class Operation(Base):
    __tablename__ = 'Operations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ExecutionInstanceID = Column(String(64), nullable=False, index=True)
    JobStep_id = Column(Integer, ForeignKey('JobSteps.id', ondelete='SET NULL'), nullable=True)
    OpType = Column(String(50), nullable=False)
    OpStatus = Column(String(20), nullable=False)
    BytesTransferred = Column(Integer, default=0)
    SourceURI = Column(Text, nullable=True)
    DestinationURI = Column(Text, nullable=True)
    Details = Column(Text, nullable=True)
    CreatedDateTime = Column(DateTime, default=datetime.datetime.utcnow)


class Audit(Base):
    __tablename__ = 'Audits'

    id = Column(Integer, primary_key=True, autoincrement=True)
    MasterObject_id = Column(Integer, ForeignKey('MasterObjects.id', ondelete='CASCADE'), nullable=True)
    ExecutionInstanceID = Column(String(64), nullable=True, index=True)
    Severity = Column(String(20), default='INFO')
    Message = Column(Text, nullable=False)
    CreatedDateTime = Column(DateTime, default=datetime.datetime.utcnow)
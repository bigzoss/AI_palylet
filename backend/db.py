import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DDL, JSON, Column, Index, Integer, String, Text, event, text
from sqlalchemy.orm import declarative_base, declared_attr, sessionmaker

from .config import settings
from .database import build_engine, database_url


def uid(prefix=""):
    return prefix + uuid4().hex[:16]


def now():
    return datetime.now(timezone.utc).isoformat()


settings.storage.mkdir(parents=True, exist_ok=True)
engine = build_engine(database_url())


Session = sessionmaker(engine, expire_on_commit=False)


class TableOptions:
    @declared_attr
    def __table_args__(cls):
        return {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"}


Base = declarative_base(cls=TableOptions)


class Project(Base):
    __tablename__ = "projects"
    id = Column(String(128), primary_key=True, default=lambda: uid("prj_"))
    name = Column(String(255), nullable=False)
    created_at = Column(String(128), default=now)


class Media(Base):
    __tablename__ = "media"
    id = Column(String(128), primary_key=True, default=lambda: uid("med_"))
    project_id = Column(String(128), nullable=False, index=True)
    kind = Column(String(128), nullable=False)
    path = Column(String(1024), nullable=False)
    name = Column(String(255), nullable=False)
    sha256 = Column(String(128), nullable=False)
    info = Column(JSON, default=dict)
    created_at = Column(String(128), default=now)


class Entity(Base):
    __tablename__ = "entities"
    id = Column(String(128), primary_key=True)
    project_id = Column(String(128), nullable=False, index=True)
    kind = Column(String(128), nullable=False)
    scope = Column(String(128), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(128), default="pending")
    content = Column(JSON, nullable=False)
    updated_at = Column(String(128), default=now)


class Revision(Base):
    __tablename__ = "revisions"
    id = Column(String(128), primary_key=True, default=lambda: uid("rev_"))
    entity_id = Column(String(128), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(JSON, nullable=False)
    status = Column(String(128), nullable=False)
    action = Column(String(128), nullable=False)
    created_at = Column(String(128), default=now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "uq_project_active_job",
            "project_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running', 'cancel_requested')"),
        ).ddl_if(dialect="sqlite"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"},
    )
    id = Column(String(128), primary_key=True, default=lambda: uid("job_"))
    project_id = Column(String(128), nullable=False, index=True)
    kind = Column(String(128), nullable=False)
    status = Column(String(128), default="queued")
    stage = Column(String(255), default="等待处理")
    progress = Column(Integer, default=0)
    payload = Column(JSON, nullable=False)
    idempotency_key = Column(String(128), unique=True, nullable=False)
    parent_id = Column(String(128), nullable=True)
    error_code = Column(String(128), nullable=True)
    error = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)
    heartbeat = Column(String(128), nullable=True)
    created_at = Column(String(128), default=now)
    updated_at = Column(String(128), default=now)


MYSQL_ACTIVE_JOB_DDL = """ALTER TABLE jobs
ADD COLUMN active_project_id VARCHAR(128)
GENERATED ALWAYS AS (CASE WHEN status IN ('queued','running','cancel_requested') THEN project_id ELSE NULL END) STORED,
ADD UNIQUE KEY uq_project_active_job (active_project_id)"""
event.listen(Job.__table__, "after_create", DDL(MYSQL_ACTIVE_JOB_DDL).execute_if(dialect="mysql"))


class StageRun(Base):
    __tablename__ = "stage_runs"
    id = Column(String(128), primary_key=True, default=lambda: uid("run_"))
    job_id = Column(String(128), nullable=False, index=True)
    project_id = Column(String(128), nullable=False, index=True)
    cache_key = Column(String(128), index=True, nullable=False)
    stage = Column(String(255), nullable=False)
    model = Column(String(255), nullable=True)
    status = Column(String(128), nullable=False)
    output = Column(JSON, nullable=True)
    usage = Column(JSON, nullable=True)
    request_id = Column(String(255), nullable=True)
    elapsed_ms = Column(Integer, nullable=True)
    created_at = Column(String(128), default=now)


def init_db():
    Base.metadata.create_all(engine)


def serialize(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False))

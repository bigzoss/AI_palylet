import json
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from backend.config import Settings
from backend.database import database_url, public_database_info
from backend.db import Base, Entity, Job, Media, Project
from backend.services import store


def test_database_configuration_handles_passwords_without_url_interpolation():
    cfg = Settings(
        _env_file=None,
        database_url="",
        mysql_host="127.0.0.1",
        mysql_port=13306,
        mysql_user="writer",
        mysql_password="test@:/#%password",
        mysql_database="framecraft",
    )
    value = database_url(cfg)
    assert value.password == "test@:/#%password"
    assert value.drivername == "mysql+pymysql" and value.query["charset"] == "utf8mb4"
    assert "test@:/#%password" not in repr(cfg)
    cfg.database_url = "mysql://writer:test-only@127.0.0.1:13306/framecraft"
    assert database_url(cfg).drivername == "mysql+pymysql"


def test_mysql_ddl_has_explicit_lengths_utf8mb4_and_no_unconditional_project_uniqueness():
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert "utf8mb4" in ddl and "InnoDB" in ddl
    job_index = next(i for i in Job.__table__.indexes if i.name == "uq_project_active_job")
    assert job_index._ddl_if.dialect == "sqlite"


@pytest.fixture
def mysql_database():
    if os.environ.get("RUN_MYSQL_TESTS") != "1":
        pytest.skip("Set RUN_MYSQL_TESTS=1 to use isolated, disposable local MySQL schemas")
    import pymysql

    from backend.config import ROOT
    from backend.database import build_engine

    value = json.loads((ROOT / ".runtime/mysql/credentials.json").read_text(encoding="utf-8"))
    name = "framecraft_test_" + uuid4().hex[:16]
    root = pymysql.connect(host="127.0.0.1", port=value["port"], user="root", password=value["root_password"])
    with root.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
    engine = build_engine(
        URL.create(
            "mysql+pymysql",
            username="root",
            password=value["root_password"],
            host="127.0.0.1",
            port=value["port"],
            database=name,
        )
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        # This unique schema was created by this fixture; never delete application databases.
        assert name.startswith("framecraft_test_") and len(name) == 32
        with root.cursor() as cursor:
            cursor.execute(f"DROP DATABASE `{name}`")
        root.close()


def test_mysql_unicode_versions_and_active_job_constraint(mysql_database):
    sessions = sessionmaker(mysql_database, expire_on_commit=False)
    with sessions() as db:
        db.add(Project(id="case_A", name="中文短剧 🎬"))
        db.add(Project(id="case_a", name="大小写不同的工程"))
        obj = store.save(
            db,
            "case_A",
            "asset",
            "source",
            {"name": "林晚", "description": "角色 🪷", "nested": {"a": [1, None, "中文"]}},
        )
        entity_id = obj.id
        first = Job(
            project_id="case_A",
            kind="analysis",
            status="queued",
            payload={"中文": True},
            idempotency_key="one",
        )
        db.add(first)
        db.commit()
        first_id = first.id
        assert db.get(Project, "case_A").name == "中文短剧 🎬"
        assert db.get(Project, "case_a").name == "大小写不同的工程"
        db.add(Job(project_id="case_A", kind="outline", status="queued", payload={}, idempotency_key="two"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.get(Job, first_id).status = "succeeded"
        db.commit()
        db.add(Job(project_id="case_A", kind="outline", status="queued", payload={}, idempotency_key="two"))
        db.commit()
        assert db.get(Entity, entity_id).content["nested"]["a"] == [1, None, "中文"]
    with sessions() as a, sessions() as b:
        old_a, old_b = a.get(Entity, entity_id), b.get(Entity, entity_id)
        store.save(
            a, "case_A", "asset", "source", {"name": "修订角色"}, entity_id=entity_id, expected=old_a.version
        )
        a.commit()
        with pytest.raises(HTTPException) as conflict:
            store.save(
                b,
                "case_A",
                "asset",
                "source",
                {"name": "过期草稿"},
                entity_id=entity_id,
                expected=old_b.version,
            )
        assert conflict.value.status_code == 409
        b.rollback()


def test_mysql_worker_claim(mysql_database, monkeypatch):
    import worker.main as worker

    sessions = sessionmaker(mysql_database, expire_on_commit=False)
    monkeypatch.setattr(worker, "Session", sessions)
    with sessions() as db:
        job = Job(project_id="p", kind="analysis", payload={}, idempotency_key="claim")
        db.add(job)
        db.commit()
        job_id = job.id
    assert worker.claim() == job_id
    assert worker.claim() is None
    with sessions() as db:
        assert db.get(Job, job_id).status == "running"


def test_sqlite_to_mysql_migration_preserves_json_and_refuses_overwrite(mysql_database, tmp_path):
    from scripts.database_admin import migrate_sqlite

    source_path = tmp_path / "source.sqlite3"
    source_engine = create_engine(URL.create("sqlite", database=str(source_path)))
    Base.metadata.create_all(source_engine)
    sessions = sessionmaker(source_engine)
    with sessions() as db:
        db.add(Project(id="migrate_project", name="迁移项目 🎬"))
        db.add(
            Media(
                id="migrate_media",
                project_id="migrate_project",
                kind="video",
                path="原片/sample.mp4",
                name="第一集.mp4",
                sha256="a" * 64,
                info={"duration_ms": 53300, "中文": [1, True, None]},
            )
        )
        db.commit()
    source_engine.dispose()
    with pytest.raises(RuntimeError, match="Stop API"):
        migrate_sqlite(source_path, mysql_database)
    report = migrate_sqlite(source_path, mysql_database, source_stopped=True)
    assert report["tables"]["projects"]["rows"] == 1
    assert report["tables"]["media"]["verified"] is True
    with mysql_database.connect() as connection:
        assert connection.scalar(select(Project.name)) == "迁移项目 🎬"
        assert connection.scalar(select(Media.info))["中文"] == [1, True, None]
        generated = connection.execute(text("SHOW COLUMNS FROM jobs LIKE 'active_project_id'")).first()
        assert generated and "STORED GENERATED" in generated.Extra
    with pytest.raises(RuntimeError, match="must be empty"):
        migrate_sqlite(source_path, mysql_database, source_stopped=True)
    assert source_path.is_file()
    assert public_database_info(mysql_database)["driver"] == "mysql"

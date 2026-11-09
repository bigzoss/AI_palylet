from fastapi import HTTPException
from sqlalchemy import select, update

from ..db import Entity, Project, Revision, clone, now, uid


def project(db, project_id):
    obj = db.get(Project, project_id)
    if not obj:
        raise HTTPException(404, "工程不存在")
    return obj


def entity(db, project_id, entity_id):
    obj = db.get(Entity, entity_id)
    if not obj or obj.project_id != project_id:
        raise HTTPException(404, "资产或文档不存在")
    return obj


def one(db, project_id, kind, scope=None):
    q = select(Entity).where(Entity.project_id == project_id, Entity.kind == kind)
    if scope:
        q = q.where(Entity.scope == scope)
    return db.scalar(q.order_by(Entity.updated_at.desc()))


def save(
    db, project_id, kind, scope, content, *, entity_id=None, expected=None, status="pending", action="edit"
):
    obj = db.get(Entity, entity_id) if entity_id else None
    if obj:
        if obj.project_id != project_id:
            raise HTTPException(404, "工程不匹配")
        version = obj.version
        if expected is None or version != expected:
            raise HTTPException(409, "版本已变化，请保留草稿并刷新后重试")
        values = dict(content=clone(content), status=status, version=version + 1, updated_at=now())
        changed = db.execute(
            update(Entity).where(Entity.id == obj.id, Entity.version == expected).values(**values)
        )
        if changed.rowcount != 1:
            raise HTTPException(409, "版本冲突")
        db.refresh(obj)
    else:
        if expected is not None:
            raise HTTPException(409, "文档不存在或已变更")
        obj = Entity(
            id=entity_id or uid(f"{scope}_"),
            project_id=project_id,
            kind=kind,
            scope=scope,
            content=clone(content),
            version=1,
            status=status,
        )
        db.add(obj)
        db.flush()
    db.add(
        Revision(
            entity_id=obj.id, version=obj.version, content=clone(obj.content), status=status, action=action
        )
    )
    db.flush()
    return obj


def invalidate(db, project_id, kinds, scope=None):
    q = select(Entity).where(
        Entity.project_id == project_id, Entity.kind.in_(kinds), Entity.status != "needs_update"
    )
    if scope:
        q = q.where(Entity.scope == scope)
    for obj in db.scalars(q).all():
        save(
            db,
            project_id,
            obj.kind,
            obj.scope,
            obj.content,
            entity_id=obj.id,
            expected=obj.version,
            status="needs_update",
            action="upstream_changed",
        )


def snapshot(db, project_id):
    from ..db import serialize

    return [serialize(x) for x in db.scalars(select(Entity).where(Entity.project_id == project_id)).all()]

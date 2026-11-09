import hashlib
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import APIStatusError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from .asset_api import register_asset_routes
from .asset_models import ImageView
from .auth import router as auth_router
from .auth import session_user
from .config import ROOT, safe_path, settings
from .database import public_database_info
from .db import (
    Entity,
    Job,
    Media,
    Project,
    Revision,
    Session,
    StageRun,
    clone,
    engine,
    init_db,
    now,
    serialize,
    uid,
)
from .schemas import (
    AdaptationCreate,
    AssetSpec,
    Brief,
    EntityUpdate,
    JobRequest,
    MergeRequest,
    Outline,
    ProjectCreate,
    ReviewRequest,
    SourceShot,
    SplitRequest,
    validate_production,
)
from .services import media, store
from .services.asset_library import image_payload, reuse_assets, source_for_brief, validate_image_links
from .services.gateway import ConfigurationError, Gateway, UncertainRequest


@asynccontextmanager
async def lifespan(_):
    init_db()
    yield


app = FastAPI(title="Framecraft · 短剧再创作工作台", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)


def database():
    with Session() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = uid("req_")
    if (
        request.url.path.startswith("/api/")
        and request.url.path
        not in {
            "/api/v1/auth/login",
            "/api/v1/auth/logout",
            "/api/v1/auth/me",
        }
        and not session_user(request)
    ):
        return JSONResponse(status_code=401, content={"message": "登录已失效，请重新登录"})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail),
            "retryable": exc.status_code >= 500,
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION",
            "message": str(exc)[:600],
            "retryable": False,
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


@app.exception_handler(RequestValidationError)
async def request_error(request, exc):
    fields = [".".join(str(x) for x in e["loc"]) for e in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION",
            "message": "请检查字段：" + "、".join(fields),
            "retryable": False,
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


@app.get("/api/v1/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ready = True
    except Exception:
        database_ready = False
    try:
        binary = media.ffmpeg()
        media_ready = bool(binary)
    except Exception:
        media_ready = False
    return {
        "status": "ok",
        "api_key_configured": bool(settings.openai_api_key),
        "media_ready": media_ready,
        "database": {**public_database_info(engine), "connected": database_ready},
        "provider": {
            "name": settings.provider_name,
            "base_url": settings.openai_base_url,
            "protocol": settings.api_mode,
        },
        "capabilities": {
            "text": bool(settings.openai_api_key and settings.openai_text_model),
            "vision": bool(settings.openai_api_key and settings.openai_vision_model),
            "image": bool(settings.openai_api_key and settings.openai_image_model),
            "transcription": bool(settings.openai_api_key and settings.openai_transcribe_model),
        },
        "transcription_note": "已配置转写模型，调用权限仍需验证"
        if settings.openai_transcribe_model
        else "此网关未配置语音转写。请上传 SRT；未上传时仅识别关键帧可见字幕，可能遗漏对白。",
        "models": {
            "vision": settings.openai_vision_model,
            "text": settings.openai_text_model,
            "transcribe": settings.openai_transcribe_model,
            "image": settings.openai_image_model,
        },
        "limits": {"upload_mb": settings.max_upload_mb, "duration_seconds": settings.max_duration_seconds},
        "mode": "live",
        "note": "未配置模型时不会返回模拟 AI 结果",
    }


@app.get("/api/v1/models")
def available_models():
    try:
        return {"provider": settings.provider_name, "data": Gateway().list_models()}
    except ConfigurationError as exc:
        raise HTTPException(409, str(exc)) from None
    except UncertainRequest:
        raise HTTPException(502, "模型列表请求超时或连接失败") from None
    except APIStatusError as exc:
        raise HTTPException(
            502, f"模型服务拒绝查询列表（HTTP {exc.status_code}），请检查密钥及地址"
        ) from None


@app.post("/api/v1/projects", status_code=201)
def create_project(body: ProjectCreate, db=Depends(database)):
    if not body.name.strip():
        raise HTTPException(422, "工程名称不能为空")
    obj = Project(name=body.name.strip())
    db.add(obj)
    db.commit()
    return serialize(obj)


@app.get("/api/v1/projects")
def projects(db=Depends(database)):
    return [serialize(x) for x in db.scalars(select(Project).order_by(Project.created_at.desc())).all()]


@app.get("/api/v1/projects/{project_id}")
def get_project(project_id: str, db=Depends(database)):
    obj = store.project(db, project_id)
    return {
        **serialize(obj),
        "entities": store.snapshot(db, project_id),
        "media": [
            serialize(x) for x in db.scalars(select(Media).where(Media.project_id == project_id)).all()
        ],
        "jobs": [
            public_job(x)
            for x in db.scalars(
                select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())
            ).all()
        ],
    }


@app.post("/api/v1/projects/{project_id}/media", status_code=201)
async def upload(project_id: str, file: UploadFile = File(...), db=Depends(database)):
    store.project(db, project_id)
    extension = Path(file.filename or "").suffix.lower()
    if extension not in {".mp4", ".mov", ".srt"}:
        raise HTTPException(415, "仅支持 MP4、MOV 或 UTF-8 SRT 文件")
    target = safe_path(f"{project_id}/uploads/{uuid4().hex}{extension}")
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, "文件超过上传大小限制")
                out.write(chunk)
        if extension == ".srt":
            # Decode and validate the format before persisting.
            media.parse_srt(target.read_text(encoding="utf-8-sig"), settings.max_duration_seconds * 1000)
            info, kind = {}, "subtitle"
        else:
            info, kind = media.probe(target), "video"
            if not 0 < info["duration_ms"] <= settings.max_duration_seconds * 1000:
                raise HTTPException(422, "视频时长必须在配置的限制范围内")
        obj = media.register(db, project_id, target, kind, Path(file.filename or target.name).name, info)
        db.commit()
        return serialize(obj)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.get("/api/v1/media/{media_id}/content")
def content(media_id: str, db=Depends(database)):
    obj = db.get(Media, media_id)
    if not obj or not safe_path(obj.path).is_file():
        raise HTTPException(404, "媒体文件不存在")
    return FileResponse(
        safe_path(obj.path), media_type=mimetypes.guess_type(obj.path)[0] or "application/octet-stream"
    )


def public_job(job):
    return {k: v for k, v in serialize(job).items() if k not in {"payload", "idempotency_key"}}


def get_job(db, job_id):
    obj = db.get(Job, job_id)
    if not obj:
        raise HTTPException(404, "任务不存在")
    return obj


def enqueue(db, project_id, kind, body, payload, parent_id=None):
    store.project(db, project_id)
    key = hashlib.sha256(f"{project_id}:{kind}:{body.idempotency_key}".encode()).hexdigest()
    previous = db.scalar(select(Job).where(Job.idempotency_key == key))
    if previous:
        return public_job(previous)
    active = db.scalar(
        select(Job).where(
            Job.project_id == project_id, Job.status.in_(["queued", "running", "cancel_requested"])
        )
    )
    if active:
        raise HTTPException(409, "该工程已有任务运行，请等待完成或取消")
    payload = clone(payload)
    payload.setdefault(
        "input_versions",
        {x.id: x.version for x in db.scalars(select(Entity).where(Entity.project_id == project_id)).all()},
    )
    job = Job(project_id=project_id, kind=kind, payload=payload, idempotency_key=key, parent_id=parent_id)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(select(Job).where(Job.idempotency_key == key))
        if duplicate:
            return public_job(duplicate)
        raise HTTPException(409, "该工程已有任务运行，请等待完成或取消") from None
    return public_job(job)


def require_approved(obj, label):
    if not obj or obj.status != "approved":
        raise HTTPException(409, f"请先审核确认{label}")


@app.post("/api/v1/projects/{project_id}/analysis-jobs", status_code=202)
def analysis_job(project_id: str, body: JobRequest, db=Depends(database)):
    obj = db.get(Media, body.media_id)
    if not obj or obj.project_id != project_id or obj.kind != "video":
        raise HTTPException(422, "请选择本工程的视频")
    if body.subtitle_id:
        sub = db.get(Media, body.subtitle_id)
        if not sub or sub.project_id != project_id or sub.kind != "subtitle":
            raise HTTPException(422, "字幕不属于本工程")
    return enqueue(db, project_id, "analysis", body, {"media_id": obj.id, "subtitle_id": body.subtitle_id})


@app.get("/api/v1/projects/{project_id}/analysis")
def analysis(project_id: str, db=Depends(database)):
    store.project(db, project_id)
    obj = store.one(db, project_id, "analysis", "source")
    return serialize(obj) if obj else None


@app.get("/api/v1/jobs/{job_id}")
def job(job_id: str, db=Depends(database)):
    return public_job(get_job(db, job_id))


@app.post("/api/v1/jobs/{job_id}/cancel")
def cancel(job_id: str, db=Depends(database)):
    obj = get_job(db, job_id)
    if obj.status == "queued":
        obj.status = "cancelled"
    elif obj.status == "running":
        obj.status = "cancel_requested"
    obj.updated_at = now()
    db.commit()
    return public_job(obj)


@app.post("/api/v1/jobs/{job_id}/retry", status_code=202)
def retry(job_id: str, body: JobRequest, db=Depends(database)):
    obj = get_job(db, job_id)
    if obj.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "只能重试失败或已取消的任务")
    for entity_id, version in obj.payload.get("input_versions", {}).items():
        current = db.get(Entity, entity_id)
        if not current or current.version != version:
            raise HTTPException(409, "输入已变化，请基于当前版本重新提交任务")
    return enqueue(db, obj.project_id, obj.kind, body, obj.payload, parent_id=obj.id)


@app.get("/api/v1/projects/{project_id}/assets")
def assets(project_id: str, scope: str | None = None, type: str | None = None, db=Depends(database)):
    store.project(db, project_id)
    query = select(Entity).where(Entity.project_id == project_id, Entity.kind == "asset")
    if scope:
        query = query.where(Entity.scope == scope)
    values = [serialize(x) for x in db.scalars(query).all()]
    return [x for x in values if not type or x["content"]["type"] == type]


def edit_entity(db, project_id, entity_id, body):
    obj = store.entity(db, project_id, entity_id)
    value = clone(body.content)
    if obj.kind == "asset":
        AssetSpec.model_validate(value)
        validate_image_links(db, project_id, value)
        if value["id"] != obj.content["id"] or value["type"] != obj.content["type"]:
            raise HTTPException(422, "不能更改资产 ID 或类型")
        for image_id in value.get("image_ids", []):
            image = db.get(Media, image_id)
            if (
                not image
                or image.project_id != project_id
                or image.kind not in {"generated", "replacement", "reference"}
            ):
                raise HTTPException(422, "图片引用无效")
    elif obj.kind == "analysis":
        for key in ("media_id", "preview_media_id", "media_sha256"):
            if value.get(key) != obj.content.get(key):
                raise HTTPException(422, "不能通过文档编辑修改媒体来源")
        valid_assets = {
            e.content["id"]
            for e in db.scalars(
                select(Entity).where(
                    Entity.project_id == project_id, Entity.kind == "asset", Entity.scope == "source"
                )
            ).all()
            if not e.content.get("merged_into")
        }
        ids = [s["id"] for s in value["shots"]]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, "镜头 ID 重复")
        for shot in value["shots"]:
            SourceShot.model_validate(shot)
            if shot["end_ms"] > db.get(Media, value["media_id"]).info["duration_ms"]:
                raise HTTPException(422, "镜头时间超出视频")
            if not set(shot["asset_ids"]).issubset(valid_assets):
                raise HTTPException(422, "镜头资产引用无效")
        store.invalidate(db, project_id, ["brief", "outline", "production", "asset"], "adaptation")
    elif obj.kind == "outline":
        Outline.model_validate(value)
        store.invalidate(db, project_id, ["production", "asset"], "adaptation")
    elif obj.kind == "brief":
        Brief.model_validate(value)
        store.invalidate(db, project_id, ["outline", "production", "asset"], "adaptation")
    elif obj.kind == "production":
        from .asset_models import RichProduction

        RichProduction.model_validate(value)
        brief = store.one(db, project_id, "brief", "adaptation")
        if not brief:
            raise HTTPException(409, "缺少再创作要求")
        validate_production(value, brief.content)
        store.invalidate(db, project_id, ["asset"], "adaptation")
        old_specs = {a["id"]: a for a in obj.content.get("assets", [])}
        for spec in value["assets"]:
            if old_specs.get(spec["id"]) == spec:
                continue
            asset_id = project_id + "_" + spec["id"]
            current_asset = db.get(Entity, asset_id)
            asset_content = {
                **(clone(current_asset.content) if current_asset else {}),
                **clone(spec),
                "image_ids": current_asset.content.get("image_ids", []) if current_asset else [],
            }
            validate_image_links(db, project_id, asset_content)
            store.save(
                db,
                project_id,
                "asset",
                "adaptation",
                asset_content,
                entity_id=asset_id,
                expected=current_asset.version if current_asset else None,
                action="production_asset_edited",
            )
    else:
        raise HTTPException(422, "不支持编辑此类文档")
    updated = store.save(
        db, project_id, obj.kind, obj.scope, value, entity_id=obj.id, expected=body.expected_version
    )
    if obj.scope == "source" and obj.kind == "asset":
        store.invalidate(db, project_id, ["analysis"], "source")
        store.invalidate(db, project_id, ["brief", "outline", "production", "asset"], "adaptation")
    db.commit()
    return serialize(updated)


@app.patch("/api/v1/projects/{project_id}/entities/{entity_id}")
def update_entity(project_id: str, entity_id: str, body: EntityUpdate, db=Depends(database)):
    return edit_entity(db, project_id, entity_id, body)


@app.patch("/api/v1/projects/{project_id}/assets/{asset_id}")
def update_asset(project_id: str, asset_id: str, body: EntityUpdate, db=Depends(database)):
    if store.entity(db, project_id, asset_id).kind != "asset":
        raise HTTPException(422, "不是资产")
    return edit_entity(db, project_id, asset_id, body)


@app.patch("/api/v1/projects/{project_id}/shots/{shot_id}")
def update_shot(project_id: str, shot_id: str, body: EntityUpdate, db=Depends(database)):
    obj = store.one(db, project_id, "analysis", "source")
    if not obj:
        raise HTTPException(404, "原片分析不存在")
    content = clone(obj.content)
    shot = next((x for x in content["shots"] if x["id"] == shot_id), None)
    if not shot:
        raise HTTPException(404, "镜头不存在")
    shot.update(
        {
            k: v
            for k, v in body.content.items()
            if k
            in {"start_ms", "end_ms", "shot_size", "camera", "action", "dialogue", "asset_ids", "uncertainty"}
        }
    )
    return edit_entity(
        db, project_id, obj.id, EntityUpdate(expected_version=body.expected_version, content=content)
    )


@app.get("/api/v1/projects/{project_id}/entities/{entity_id}/revisions")
def revisions(project_id: str, entity_id: str, db=Depends(database)):
    store.entity(db, project_id, entity_id)
    return [
        serialize(x)
        for x in db.scalars(
            select(Revision).where(Revision.entity_id == entity_id).order_by(Revision.version.desc())
        ).all()
    ]


@app.post("/api/v1/projects/{project_id}/reviews")
def review(project_id: str, body: ReviewRequest, db=Depends(database)):
    obj = store.entity(db, project_id, body.entity_id)
    if body.status == "approved" and obj.kind in {"outline", "production"}:
        dependency = store.one(db, project_id, "brief" if obj.kind == "outline" else "outline", "adaptation")
        require_approved(dependency, "上游要求／大纲")
    obj = store.save(
        db,
        project_id,
        obj.kind,
        obj.scope,
        obj.content,
        entity_id=obj.id,
        expected=body.expected_version,
        status=body.status,
        action="review_" + body.status,
    )
    if body.status != "approved":
        if obj.scope == "source":
            store.invalidate(db, project_id, ["brief", "outline", "production", "asset"], "adaptation")
        elif obj.kind in {"brief", "outline"}:
            store.invalidate(
                db,
                project_id,
                ["production", "asset"] + (["outline"] if obj.kind == "brief" else []),
                "adaptation",
            )
    db.commit()
    return serialize(obj)


@app.post("/api/v1/projects/{project_id}/asset-merges")
def merge(project_id: str, body: MergeRequest, db=Depends(database)):
    a, b = store.entity(db, project_id, body.source_id), store.entity(db, project_id, body.target_id)
    if (
        a.id == b.id
        or a.kind != "asset"
        or b.kind != "asset"
        or a.scope != b.scope
        or a.content["type"] != b.content["type"]
    ):
        raise HTTPException(422, "只能合并同工程、同范围、同类型的不同资产")
    if a.version != body.source_version or b.version != body.target_version:
        raise HTTPException(409, "资产版本发生变化")
    value = clone(b.content)
    value["evidence"] += a.content.get("evidence", [])
    value["image_ids"] = list(dict.fromkeys(value.get("image_ids", []) + a.content.get("image_ids", [])))
    store.save(
        db, project_id, "asset", b.scope, value, entity_id=b.id, expected=b.version, action="merge_target"
    )
    av = clone(a.content)
    av["merged_into"] = b.content["id"]
    store.save(
        db,
        project_id,
        "asset",
        a.scope,
        av,
        entity_id=a.id,
        expected=a.version,
        status="rejected",
        action="merge_source",
    )
    documents = db.scalars(
        select(Entity).where(
            Entity.project_id == project_id,
            Entity.scope == a.scope,
            Entity.kind.in_(["analysis", "production", "script"]),
        )
    ).all()
    for document in documents:
        value = clone(document.content)
        changed = False
        for shot in value.get("shots", []):
            if a.content["id"] in shot["asset_ids"]:
                changed = True
                shot["asset_ids"] = list(
                    dict.fromkeys(b.content["id"] if x == a.content["id"] else x for x in shot["asset_ids"])
                )
        for scene in value.get("scenes", []):
            for key in ("character_ids", "prop_ids"):
                if a.content["id"] in scene[key]:
                    changed = True
                    scene[key] = list(
                        dict.fromkeys(b.content["id"] if x == a.content["id"] else x for x in scene[key])
                    )
            if scene["location_asset_id"] == a.content["id"]:
                changed = True
                scene["location_asset_id"] = b.content["id"]
        if changed:
            if "assets" in value:
                value["assets"] = [
                    x for x in value["assets"] if x["id"] != a.content["id"] and x["id"] != b.content["id"]
                ] + [clone(b.content)]
            store.save(
                db,
                project_id,
                document.kind,
                document.scope,
                value,
                entity_id=document.id,
                expected=document.version,
                action="merge_refs",
            )
    if a.scope == "source":
        store.invalidate(db, project_id, ["brief", "outline", "production", "asset"], "adaptation")
    db.commit()
    return {"merged": True}


@app.post("/api/v1/projects/{project_id}/assets/{asset_id}/split", status_code=201)
def split_asset(project_id: str, asset_id: str, body: SplitRequest, db=Depends(database)):
    obj = store.entity(db, project_id, asset_id)
    if obj.kind != "asset" or obj.scope != "source" or obj.version != body.expected_version:
        raise HTTPException(409, "只能按当前版本拆分原片资产")
    document = store.one(db, project_id, "analysis", "source")
    if not document:
        raise HTTPException(404, "原片分析不存在")
    value = clone(document.content)
    matching = [s for s in value["shots"] if s["id"] in body.shot_ids and obj.content["id"] in s["asset_ids"]]
    if len(matching) != len(set(body.shot_ids)):
        raise HTTPException(422, "请选择引用此资产的有效镜头")
    prefix = {"character": "CHAR", "scene": "SCENE", "prop": "PROP"}[obj.content["type"]]
    local_id = "SRC_" + prefix + "_" + uid()[:8]
    new_content = clone(obj.content)
    new_content.update(
        id=local_id,
        name=body.name,
        image_ids=[],
        image_views={},
        reference_image_ids=[],
        evidence=[e for e in obj.content.get("evidence", []) if e["shot_id"] in body.shot_ids],
    )
    source_content = clone(obj.content)
    source_content["evidence"] = [
        e for e in source_content.get("evidence", []) if e["shot_id"] not in body.shot_ids
    ]
    for shot in matching:
        shot["asset_ids"] = [local_id if x == obj.content["id"] else x for x in shot["asset_ids"]]
    store.save(
        db,
        project_id,
        "asset",
        "source",
        source_content,
        entity_id=obj.id,
        expected=obj.version,
        action="split_source",
    )
    created = store.save(
        db,
        project_id,
        "asset",
        "source",
        new_content,
        entity_id=project_id + "_" + local_id,
        action="split_created",
    )
    store.save(
        db,
        project_id,
        "analysis",
        "source",
        value,
        entity_id=document.id,
        expected=document.version,
        action="split_refs",
    )
    store.invalidate(db, project_id, ["brief", "outline", "production", "asset"], "adaptation")
    db.commit()
    return serialize(created)


@app.post("/api/v1/projects/{project_id}/adaptations", status_code=201)
def adaptation(project_id: str, body: AdaptationCreate, db=Depends(database)):
    source = (
        store.entity(db, project_id, body.source_entity_id)
        if body.source_entity_id
        else store.one(db, project_id, "analysis", "source")
    )
    if source and source.kind not in {"analysis", "script"}:
        raise HTTPException(422, "创作来源应为原片分析或解析后的剧本")
    require_approved(source, "原片或剧本分析")
    if source.version != body.expected_source_version:
        raise HTTPException(409, "原片分析版本发生变化")
    brief_content = body.brief.model_dump()
    brief_content["_source_entity_id"] = source.id
    brief_content["_source_version"] = source.version
    reused = (
        reuse_assets(db, project_id, body.brief.reuse_asset_ids)
        if body.brief.asset_strategy == "reuse"
        else []
    )
    if (
        sum(x.content["type"] == "character" for x in reused) > body.brief.max_characters
        or sum(x.content["type"] == "scene" for x in reused) > body.brief.max_scenes
    ):
        raise HTTPException(422, "沿用的角色或场景数超过制作限制，请调整选择或数量上限")
    brief_content["_reused_asset_ids"] = [x.id for x in reused]
    brief_content["_reused_assets"] = [clone(x.content) for x in reused]
    old = store.one(db, project_id, "brief", "adaptation")
    store.invalidate(db, project_id, ["outline", "production", "asset"], "adaptation")
    obj = store.save(
        db,
        project_id,
        "brief",
        "adaptation",
        brief_content,
        entity_id=old.id if old else None,
        expected=old.version if old else None,
        status="approved",
        action="brief_confirmed",
    )
    db.commit()
    return serialize(obj)


@app.post("/api/v1/adaptations/{adaptation_id}/outline-jobs", status_code=202)
def outline_job(adaptation_id: str, body: JobRequest, db=Depends(database)):
    brief = db.get(Entity, adaptation_id)
    if not brief or brief.kind != "brief":
        raise HTTPException(404, "再创作要求不存在")
    require_approved(brief, "再创作要求")
    source = source_for_brief(db, brief.project_id, brief)
    source_content = clone(source.content)
    if source.kind == "script":
        source_content["assets"] = [
            clone(x.content)
            for x in db.scalars(
                select(Entity).where(
                    Entity.project_id == brief.project_id, Entity.kind == "asset", Entity.scope == "source"
                )
            ).all()
            if x.content.get("origin_id") == source.id
            and not x.content.get("merged_into")
            and not x.content.get("retired")
        ]
    return enqueue(db, brief.project_id, "outline", body, {"brief": brief.content, "source": source_content})


@app.post("/api/v1/adaptations/{adaptation_id}/production-jobs", status_code=202)
def production_job(adaptation_id: str, body: JobRequest, db=Depends(database)):
    brief = db.get(Entity, adaptation_id)
    if not brief or brief.kind != "brief":
        raise HTTPException(404, "再创作要求不存在")
    require_approved(brief, "再创作要求")
    outline = store.one(db, brief.project_id, "outline", "adaptation")
    require_approved(outline, "故事大纲")
    return enqueue(
        db,
        brief.project_id,
        "production",
        body,
        {
            "brief": brief.content,
            "outline": outline.content,
            "reused_assets": [
                serialize(store.entity(db, brief.project_id, x))
                for x in brief.content.get("_reused_asset_ids", [])
            ],
        },
    )


@app.post("/api/v1/projects/{project_id}/assets/{asset_id}/image-jobs", status_code=202)
def image_job(project_id: str, asset_id: str, body: JobRequest, db=Depends(database)):
    obj = store.entity(db, project_id, asset_id)
    if obj.kind != "asset":
        raise HTTPException(422, "请选择资产")
    if body.expected_version != obj.version:
        raise HTTPException(409, "资产版本已变化")
    return enqueue(db, project_id, "image", body, image_payload(db, project_id, [obj], body.image_view))


@app.post("/api/v1/projects/{project_id}/assets/{asset_id}/images", status_code=201)
async def replace_image(
    project_id: str,
    asset_id: str,
    expected_version: int,
    image_view: ImageView = "sheet",
    file: UploadFile = File(...),
    db=Depends(database),
):
    obj = store.entity(db, project_id, asset_id)
    if obj.kind != "asset":
        raise HTTPException(422, "不是资产")
    if obj.version != expected_version:
        raise HTTPException(409, "资产版本发生变化")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(415, "请上传 PNG、JPEG 或 WebP")
    path = safe_path(f"{project_id}/replacement/{uid()}{ext}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = await file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(413, "图片不能超过 20MB")
        path.write_bytes(data)
        media.verify_image(path)
        record = media.register(db, project_id, path, "replacement")
        value = clone(obj.content)
        value["image_ids"] = [record.id] + value.get("image_ids", [])
        value["image_views"] = {**value.get("image_views", {}), image_view: record.id}
        obj = store.save(
            db,
            project_id,
            "asset",
            obj.scope,
            value,
            entity_id=obj.id,
            expected=expected_version,
            action="image_replaced",
        )
        db.commit()
        return serialize(obj)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.post("/api/v1/projects/{project_id}/exports", status_code=202)
def export_job(project_id: str, body: JobRequest, db=Depends(database)):
    obj = store.project(db, project_id)
    entities = store.snapshot(db, project_id)
    if not entities:
        raise HTTPException(409, "暂无可导出内容")
    return enqueue(
        db,
        project_id,
        "export",
        body,
        {
            "project": serialize(obj),
            "entities": entities,
            "media": [
                serialize(x) for x in db.scalars(select(Media).where(Media.project_id == project_id)).all()
            ],
            "revisions": [
                serialize(x)
                for x in db.scalars(
                    select(Revision).where(Revision.entity_id.in_([e["id"] for e in entities]))
                ).all()
            ],
            "include_reference": body.include_reference,
        },
    )


@app.get("/api/v1/exports/{export_id}/download")
def download(export_id: str, db=Depends(database)):
    obj = get_job(db, export_id)
    if obj.kind != "export" or obj.status != "succeeded" or not obj.result:
        raise HTTPException(409, "导出包尚未准备好")
    return FileResponse(
        safe_path(obj.result["path"]), filename=f"drama_{export_id}.zip", media_type="application/zip"
    )


@app.get("/api/v1/projects/{project_id}/runs")
def runs(project_id: str, db=Depends(database)):
    store.project(db, project_id)
    return [
        {k: v for k, v in serialize(x).items() if k != "output"}
        for x in db.scalars(
            select(StageRun).where(StageRun.project_id == project_id).order_by(StageRun.created_at.desc())
        ).all()
    ]


register_asset_routes(app, database, enqueue)


# Serve a built SPA locally. Unknown API URLs must remain JSON 404s.
dist = ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith(("api/", "docs", "openapi")):
        raise HTTPException(404, "接口不存在")
    if dist.exists():
        target = (dist / path).resolve()
        if target.is_relative_to(dist.resolve()) and target.is_file():
            return FileResponse(target)
        return FileResponse(dist / "index.html")
    raise HTTPException(404, "前端尚未构建，请先启动 Vite 或构建前端")

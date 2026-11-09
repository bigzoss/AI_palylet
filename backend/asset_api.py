from pathlib import Path

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from .asset_models import VIEWS, AssetCreate, AssetTaskRequest, ScriptInput, ScriptParseRequest
from .config import safe_path
from .db import Entity, Media, serialize
from .services import store
from .services.asset_library import asset_id, filename, image_payload, reuse_assets, script_file_text


def register_asset_routes(app, database, enqueue):
    @app.post("/api/v1/projects/{project_id}/assets", status_code=201)
    def create_asset(project_id: str, body: AssetCreate, db=Depends(database)):
        store.project(db, project_id)
        content = body.model_dump(exclude={"scope"})
        content.update(
            id=asset_id(body.scope, body.type),
            evidence=[],
            image_ids=[],
            image_views={},
            reference_image_ids=[],
            profile_origin="manual",
            origin_kind="manual",
        )
        obj = store.save(
            db,
            project_id,
            "asset",
            body.scope,
            content,
            entity_id=project_id + "_" + content["id"],
            action="asset_created",
        )
        db.commit()
        return serialize(obj)

    def selected(db, project_id, body):
        ids = list(dict.fromkeys(body.asset_ids))
        objects = [store.entity(db, project_id, entity_id) for entity_id in ids]
        for obj in objects:
            if obj.kind != "asset" or obj.content.get("merged_into"):
                raise HTTPException(422, "请选择有效资产")
            if body.expected_versions.get(obj.id) != obj.version:
                raise HTTPException(409, "所选资产版本已变化，请刷新后重试")
        return objects

    @app.post("/api/v1/projects/{project_id}/asset-profile-jobs", status_code=202)
    def profile_job(project_id: str, body: AssetTaskRequest, db=Depends(database)):
        objects = selected(db, project_id, body)
        if any(x.content["type"] != "character" for x in objects):
            raise HTTPException(422, "人物档案任务仅支持角色资产")
        return enqueue(db, project_id, "profiles", body, {"assets": [serialize(x) for x in objects]})

    @app.post("/api/v1/projects/{project_id}/asset-image-jobs", status_code=202)
    def images_job(project_id: str, body: AssetTaskRequest, db=Depends(database)):
        return enqueue(
            db,
            project_id,
            "image",
            body,
            image_payload(db, project_id, selected(db, project_id, body), body.image_view),
        )

    @app.post("/api/v1/projects/{project_id}/reuse-assets", status_code=201)
    def reuse(project_id: str, body: AssetTaskRequest, db=Depends(database)):
        selected(db, project_id, body)
        copies = reuse_assets(db, project_id, list(dict.fromkeys(body.asset_ids)))
        db.commit()
        return [serialize(x) for x in copies]

    def save_script_input(db, project_id, value):
        store.project(db, project_id)
        old = store.one(db, project_id, "script_input", "source")
        if old and value.expected_version != old.version:
            raise HTTPException(409, "剧本已被修改，请保留草稿并刷新确认最新版本")
        content = value.model_dump(exclude={"expected_version"})
        content["text"] = content["text"].replace("\r\n", "\n")
        obj = store.save(
            db,
            project_id,
            "script_input",
            "source",
            content,
            entity_id=old.id if old else None,
            expected=old.version if old else None,
            action="script_imported",
        )
        store.invalidate(db, project_id, ["script"], "source")
        document = store.one(db, project_id, "script", "source")
        if document:
            for asset in db.scalars(
                select(Entity).where(
                    Entity.project_id == project_id, Entity.kind == "asset", Entity.scope == "source"
                )
            ).all():
                if asset.content.get("origin_id") == document.id and not asset.content.get("retired"):
                    store.save(
                        db,
                        project_id,
                        "asset",
                        "source",
                        asset.content,
                        entity_id=asset.id,
                        expected=asset.version,
                        status="needs_update",
                        action="script_input_changed",
                    )
        store.invalidate(db, project_id, ["brief", "outline", "production"], "adaptation")
        db.commit()
        return serialize(obj)

    @app.post("/api/v1/projects/{project_id}/scripts", status_code=201)
    def save_script(project_id: str, body: ScriptInput, db=Depends(database)):
        return save_script_input(db, project_id, body)

    @app.post("/api/v1/projects/{project_id}/script-files", status_code=201)
    async def import_script(
        project_id: str,
        expected_version: int | None = None,
        file: UploadFile = File(...),
        db=Depends(database),
    ):
        try:
            value = await file.read(2 * 1024 * 1024 + 1)
            try:
                text = script_file_text(file.filename or "", value)
            except ValueError:
                raise
            except Exception:
                raise ValueError("无法读取剧本，请检查文档是否完整或改为粘贴文本") from None
            return save_script_input(
                db,
                project_id,
                ScriptInput(
                    title=Path(file.filename or "导入剧本").stem[:100],
                    text=text,
                    expected_version=expected_version,
                ),
            )
        finally:
            await file.close()

    @app.post("/api/v1/projects/{project_id}/script-parse-jobs", status_code=202)
    def parse_job(project_id: str, body: ScriptParseRequest, db=Depends(database)):
        source = (
            store.entity(db, project_id, body.entity_id)
            if body.entity_id
            else store.one(db, project_id, "script_input", "source")
        )
        if not source or source.kind != "script_input":
            raise HTTPException(409, "请先保存剧本")
        if source.version != body.expected_version:
            raise HTTPException(409, "剧本版本已变化，请先保存最新文本")
        return enqueue(db, project_id, "script_parse", body, {"script_input": serialize(source)})

    @app.get("/api/v1/projects/{project_id}/assets/{entity_id}/images/{view}/download")
    def download_view(project_id: str, entity_id: str, view: str, db=Depends(database)):
        obj = store.entity(db, project_id, entity_id)
        if obj.kind != "asset" or view not in VIEWS:
            raise HTTPException(422, "请选择有效图片视图")
        image_id = obj.content.get("image_views", {}).get(view)
        if not image_id:
            raise HTTPException(404, "该视图尚未生成或上传")
        image = db.get(Media, image_id)
        if not image or image.project_id != project_id or not safe_path(image.path).is_file():
            raise HTTPException(404, "图片不存在")
        return FileResponse(
            safe_path(image.path),
            filename=filename(obj.content["name"]) + "_" + view + Path(image.path).suffix,
        )

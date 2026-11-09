import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

from ..config import safe_path
from ..db import now
from .asset_library import PROFILE_LABELS, VIEWS, filename


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def build_export(project, entities, media, export_id, include_reference=False, revisions=None):
    files = {}
    by_media = {m["id"]: m for m in media}
    unresolved = []
    if not any(e["kind"] == "production" for e in entities):
        unresolved.append({"id": project["id"], "status": "new_production_missing"})
    asset_index = {(e["scope"], e["content"].get("id")): e for e in entities if e["kind"] == "asset"}
    for obj in entities:
        if obj["kind"] == "asset" and (obj["content"].get("merged_into") or obj["content"].get("retired")):
            continue
        content = obj["content"]
        scope = "source_analysis" if obj["scope"] == "source" else "adaptation"
        if obj["status"] != "approved":
            unresolved.append({"id": obj["id"], "kind": obj["kind"], "status": obj["status"]})
        files[f"{scope}/{obj['kind']}_{obj['id']}.json"] = json_bytes(obj)
        if obj["kind"] in ("analysis", "production"):
            for shot in content.get("shots", []):
                references = []
                for asset_id in shot.get("asset_ids", []):
                    asset = asset_index.get((obj["scope"], asset_id))
                    if not asset or asset["content"].get("merged_into"):
                        raise ValueError("导出失败：分镜包含无效资产引用")
                    references.append(
                        {"asset_id": asset_id, "entity_id": asset["id"], "version": asset["version"]}
                    )
                shot["asset_refs"] = references
            # Resolve asset links against this export's frozen versions.
            files[f"{scope}/{obj['kind']}_{obj['id']}.json"] = json_bytes(obj)
            output = io.StringIO(newline="")
            shots = content.get("shots", [])
            keys = [
                "id",
                "start_ms",
                "end_ms",
                "planned_duration_ms",
                "shot_size",
                "camera",
                "action",
                "dialogue",
                "sound",
                "asset_ids",
            ]
            writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            for shot in shots:
                row = {
                    k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                    for k, v in shot.items()
                }
                # Prevent spreadsheet formula execution when opening exported CSV.
                row = {
                    k: ("'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v)
                    for k, v in row.items()
                }
                writer.writerow(row)
            files[f"{scope}/storyboard.csv"] = output.getvalue().encode("utf-8-sig")
            if obj["kind"] == "production":
                files["adaptation/script.md"] = content.get("script", "").encode("utf-8")
        if obj["kind"] == "outline":
            files["adaptation/outline.md"] = (
                "# "
                + content.get("title", "")
                + "\n\n"
                + content.get("logline", "")
                + "\n\n"
                + "\n".join(content.get("beats", []))
            ).encode("utf-8")
        if obj["kind"] == "script":
            files[f"{scope}/original_script.md"] = content.get("text", "").encode("utf-8")
            files[f"{scope}/script_scenes.json"] = json_bytes(content.get("scenes", []))
        if obj["kind"] == "asset":
            asset_dir = f"assets/{obj['scope']}/{content['type']}/{obj['id']}/v{obj['version']:03}"
            files[f"{asset_dir}/asset.json"] = json_bytes(obj)
            files[f"{asset_dir}/prompt.md"] = content.get("prompt", "").encode("utf-8")
            if content["type"] == "character":
                profile = content.get("profile") or {}
                files[f"{asset_dir}/人物档案.md"] = (
                    "# "
                    + content["name"]
                    + "\n\n"
                    + content.get("description", "")
                    + "\n\n"
                    + "\n\n".join(
                        f"## {label}\n\n{profile.get(key) or '待补充'}"
                        for key, label in PROFILE_LABELS.items()
                    )
                    + "\n\n创作补全字段："
                    + "、".join(PROFILE_LABELS.get(k, k) for k in profile.get("inferred_fields", []))
                    + "\n\n待确认字段："
                    + "、".join(PROFILE_LABELS.get(k, k) for k in profile.get("unknown_fields", []))
                ).encode("utf-8")
            for view, image_id in content.get("image_views", {}).items():
                m = by_media.get(image_id)
                if view in VIEWS and m and (include_reference or m["kind"] != "reference"):
                    path = safe_path(m["path"])
                    if path.is_file():
                        files[f"{asset_dir}/{filename(content['name'])}_{view}{path.suffix}"] = (
                            path.read_bytes()
                        )
            for media_id in content.get("image_ids", []):
                m = by_media.get(media_id)
                if not m:
                    unresolved.append({"id": obj["id"], "status": "missing_image"})
                    continue
                if m["kind"] == "reference" and not include_reference:
                    continue
                path = safe_path(m["path"])
                if path.is_file():
                    files[f"{asset_dir}/{m['id']}{path.suffix}"] = path.read_bytes()
                else:
                    unresolved.append({"id": obj["id"], "status": "missing_file"})
            if obj["scope"] == "adaptation" and not content.get("image_ids"):
                unresolved.append({"id": obj["id"], "status": "image_not_generated"})
    files["review/unresolved_items.json"] = json_bytes(unresolved)
    files["review/change_log.json"] = json_bytes(revisions or [])
    files["README_导入说明.md"] = (
        "# 创作包\n\n这是通用创作包，不是已经验证的火山剧创直接导入格式。\n"
        "先阅读 adaptation 的大纲、剧本和分镜，再将 assets/adaptation 中审核通过的图片和描述人工迁移到工作台。\n"
        "source_analysis 是原片提取资料，与新剧资产分开。\n"
        "人物档案.md 保存人物设定；角色名_sheet 为肖像与正侧背组合卡，portrait/front/side/back 为独立视图。\n"
        "script_scenes.json 保存场次、人物关联与原文定位。未知与创作补全字段需人工确认。\n"
        "未审核、需更新、缺图片等内容列在 review/unresolved_items.json 中。\n"
    ).encode("utf-8")
    manifest = {
        "format_version": "1.0",
        "project_id": project["id"],
        "project_name": project["name"],
        "created_at": now(),
        "draft": bool(unresolved),
        "adapter": "generic-manual-v1",
        "revisions": {x["id"]: x["version"] for x in entities},
        "files": [
            {"path": k, "sha256": hashlib.sha256(v).hexdigest(), "bytes": len(v)} for k, v in files.items()
        ],
    }
    files["manifest.json"] = json_bytes(manifest)
    target = safe_path(f"{project['id']}/exports/{export_id}.zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("导出路径无效")
            archive.writestr(name, data)
    return {"path": target.relative_to(safe_path(".")).as_posix(), "manifest": manifest}

import io
import re
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from fastapi import HTTPException

from ..asset_models import VIEWS, CharacterProfile
from ..db import Media, clone, uid
from . import store

PROFILE_LABELS = {
    "role_type": "角色定位",
    "identity": "身份职业",
    "age": "年龄段",
    "gender": "性别",
    "personality": "性格",
    "motivation": "目标动机",
    "backstory": "人物背景",
    "relationships": "人物关系",
    "appearance": "面容外貌",
    "hairstyle": "发型",
    "body": "体态",
    "clothing": "服装配饰",
    "voice": "声音",
    "performance": "表演习惯",
    "consistency": "一致性约束",
}


def asset_id(scope, kind):
    return (
        ("SRC_" if scope == "source" else "NEW_")
        + {"character": "CHAR", "scene": "SCENE", "prop": "PROP"}[kind]
        + "_"
        + uid()
    )


def character_prompt(content, view="sheet"):
    profile = content.get("profile") or {}
    details = "\n".join(
        f"{label}：{profile[key]}" for key, label in PROFILE_LABELS.items() if profile.get(key)
    )
    if content["type"] != "character":
        return f"独立{content['type']}制作资产，干净背景，无文字水印。{content['name']}：{content['description']}\n{content.get('prompt', '')}"
    composition = (
        "一张横向角色标准设定图，清晰分为四个不重叠的区域：左侧是头肩高清肖像，右侧依次是正面全身、侧面全身、背面全身。"
        "所有视角必须是同一个人物、同一套服装、同一发型和配饰；全身从头到脚完整可见。"
        if view == "sheet"
        else f"只绘制一个人物的{VIEWS[view]}，{'头肩特写' if view == 'portrait' else '从头到脚完整可见，站立自然姿态'}。"
    )
    orientation = {
        "portrait": "最终画面要求：只生成一个头肩高清肖像，保留同一张脸、发型与衣领。",
        "front": "最终画面要求：只生成一张严格正面全身照。脸、胸部、膝盖和脚尖全部正对镜头，双肩对称。从头顶到鞋完整可见。FRONT VIEW ONLY, body facing camera straight on.",
        "side": "最终画面要求：将同一人物旋转90度，朝画面左侧站立。只显示一只眼和鼻子的侧轮廓，肩膀与髋部前后叠合，从头顶到鞋完整可见。只生成一个严格侧面人物。STRICT 90 DEGREE SIDE PROFILE VIEW ONLY.",
        "back": "最终画面要求：将同一人物转过身背向镜头。相机只看到后脑勺、后背、衣服背部和鞋后跟。头与身体都背向镜头，不回头，脸和胸前完全不可见。从头顶到鞋完整可见。只生成一个背面人物。BACK VIEW ONLY, FACE NOT VISIBLE.",
        "sheet": "最终画面必须同时包括肖像、正面全身、侧面全身、背面全身四个不同区域。",
    }[view]
    return (
        f"制作角色 {content['name']} 的专业影视人物形象资产。{composition}"
        "中性浅灰纯色背景，均匀棚拍光，写实摄影，高清细节，无文字、无水印、无多余人物。"
        "如果提供参考图，根据下列描述只选择对应人物，去除其他人物、场景和字幕。"
        "未在参考中出现的身体或视角属于创作补全，保持已知特征一致。\n"
        "全身视图人物居中、双臂自然下垂，左右留白各不少于25%，头顶和鞋底留少量空隙。\n"
        f"形象描述：{content['description']}\n{details}\n补充要求：{content.get('prompt', '')}"
        "\n以上描述只规定人物身份、服装与风格，画面的视角和人数以下述要求为准：\n" + orientation
    )


def image_payload(db, project_id, entities, view):
    references = {}
    for obj in entities:
        ids = (
            obj.content.get("reference_image_ids", [])
            + list((obj.content.get("image_views") or {}).values())
            + obj.content.get("image_ids", [])
        )
        for image_id in ids:
            image = db.get(Media, image_id)
            if image and image.project_id == project_id:
                references[obj.id] = image.path
                break
    from ..db import serialize

    return {"assets": [serialize(obj) for obj in entities], "image_view": view, "references": references}


def validate_image_links(db, project_id, content):
    views = content.get("image_views") or {}
    if not isinstance(views, dict) or not set(views).issubset(VIEWS):
        raise ValueError("图片视图类型无效")
    ids = set(content.get("image_ids", []) + content.get("reference_image_ids", []) + list(views.values()))
    for image_id in ids:
        obj = db.get(Media, image_id)
        if (
            not obj
            or obj.project_id != project_id
            or obj.kind not in {"generated", "replacement", "reference"}
        ):
            raise ValueError("图片引用不属于本工程")
    if content.get("profile") is not None:
        CharacterProfile.model_validate(content["profile"])


def script_file_text(name, data):
    suffix = Path(name).suffix.lower()
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("剧本文件不能超过 2 MB")
    if suffix in {".txt", ".md"}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("gb18030")
    elif suffix == ".docx":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 2 * 1024 * 1024:
                raise ValueError("Word 正文过大，请按单集导入")
            xml = archive.read(info)
        if b"<!DOCTYPE" in xml.upper():
            raise ValueError("不支持带 DTD 的文档")
        tree = ElementTree.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        text = "\n".join(
            "".join(n.text or "" for n in p.findall(".//w:t", ns)) for p in tree.findall(".//w:p", ns)
        )
    else:
        raise ValueError("支持 TXT、Markdown、DOCX，或直接粘贴剧本")
    text = text.replace("\r\n", "\n").strip()
    if not 20 <= len(text) <= 20000:
        raise ValueError("请导入 20～20,000 字的单集剧本")
    return text


def reuse_assets(db, project_id, ids):
    copied = []
    for entity_id in ids:
        original = store.entity(db, project_id, entity_id)
        if original.kind != "asset" or original.content.get("merged_into"):
            raise HTTPException(422, "请选择有效资产")
        if original.scope == "adaptation":
            copied.append(original)
            continue
        content = clone(original.content)
        content["id"] = asset_id("adaptation", content["type"])
        content["reused_from"] = {"entity_id": original.id, "version": original.version}
        copied.append(
            store.save(
                db,
                project_id,
                "asset",
                "adaptation",
                content,
                entity_id=project_id + "_" + content["id"],
                action="reused_asset",
            )
        )
    return copied


def source_for_brief(db, project_id, brief):
    source_id = brief.content.get("_source_entity_id")
    source = (
        store.entity(db, project_id, source_id)
        if source_id
        else store.one(db, project_id, "analysis", "source")
    )
    if not source or source.kind not in {"analysis", "script"} or source.status != "approved":
        raise HTTPException(409, "请先审核确认作为创作来源的原片或剧本")
    return source


def validate_script_breakdown(value, text):
    assets = {a["id"]: a for a in value["assets"]}
    if len(assets) != len(value["assets"]) or len(assets) > 40:
        raise ValueError("剧本资产 ID 重复或数量超过 40 项")
    if len(
        {(a["type"], unicodedata.normalize("NFKC", a["name"]).strip().casefold()) for a in value["assets"]}
    ) != len(assets):
        raise ValueError("同类同名资产重复，请归并同一角色或为不同造型明确命名")
    if not value["scenes"] or len(value["scenes"]) > 60:
        raise ValueError("剧本需包含 1～60 个可定位的场次")
    if len({s["id"] for s in value["scenes"]}) != len(value["scenes"]):
        raise ValueError("场次 ID 重复")
    for asset in assets.values():
        if not asset["id"].startswith("SRC_"):
            raise ValueError("剧本提取资产 ID 必须以 SRC_ 开头")
        if asset["type"] == "character" and not asset.get("profile"):
            raise ValueError("每个人物必须包含完整档案，缺失信息写未知并标注")
        if asset["type"] == "character":
            validate_profile(asset["profile"])
        if asset.get("evidence"):
            raise ValueError("剧本没有视频时间码，证据应通过场次原文定位，evidence 留空")
    for scene in value["scenes"]:
        if not scene["source_quote"].strip() or scene["source_quote"] not in text:
            raise ValueError(f"场次 {scene['id']} 的 source_quote 必须逐字引用剧本原文")
        links = [(scene["location_asset_id"], "scene")] if scene["location_asset_id"] else []
        links += [(x, "character") for x in scene["character_ids"]] + [(x, "prop") for x in scene["prop_ids"]]
        if any(x not in assets or assets[x]["type"] != kind for x, kind in links):
            raise ValueError("场次关联的角色、场景或道具不存在，或类型不匹配")


def validate_profile(value):
    CharacterProfile.model_validate(value)
    missing = [label for key, label in PROFILE_LABELS.items() if not value.get(key, "").strip()]
    if missing:
        raise ValueError("人物档案字段需要填写，缺失事实写未知并标记：" + "、".join(missing))
    if any(
        k not in PROFILE_LABELS for k in value.get("inferred_fields", []) + value.get("unknown_fields", [])
    ):
        raise ValueError("人物档案的补全或待确认字段名称不正确")


def filename(name):
    return re.sub(r'[\\/:*?"<>|\r\n]', "_", name)[:100]

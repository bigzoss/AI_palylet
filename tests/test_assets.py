import copy
import io
import json
import zipfile

import pytest
from test_workflow import FakeGateway, approve, create_project, job_body, run_job

from backend.asset_models import CharacterProfile, ScriptBreakdown
from backend.db import Entity, Session
from backend.schemas import Production
from backend.services.asset_library import PROFILE_LABELS, script_file_text, validate_script_breakdown
from backend.services.media import compose_character_sheet
from backend.workflows import Workflow

TEXT = "第1场，旧书店，夜。小林穿蓝色衬衫，将一张旧照片放在柜台上。小林说：“这张照片上的人，你认识吗？”"
PROFILE = {
    **{key: "未知" for key in PROFILE_LABELS},
    "identity": "书店访客",
    "clothing": "蓝色衬衫",
    "unknown_fields": ["age", "voice"],
}


def breakdown():
    return {
        "title": "旧照片",
        "synopsis": "小林在书店寻找线索",
        "assets": [
            {
                "id": "SRC_CHAR_001",
                "type": "character",
                "name": "小林",
                "description": "身穿蓝色衬衫的书店访客",
                "prompt": "写实摄影",
                "profile": PROFILE,
                "evidence": [],
            },
            {
                "id": "SRC_SCENE_001",
                "type": "scene",
                "name": "旧书店",
                "description": "夜间的旧书店",
                "prompt": "写实内景",
                "evidence": [],
                "profile": None,
            },
        ],
        "scenes": [
            {
                "id": "SC_001",
                "title": "书店寻人",
                "location_asset_id": "SRC_SCENE_001",
                "character_ids": ["SRC_CHAR_001"],
                "prop_ids": [],
                "action": "小林询问照片线索",
                "dialogue": "这张照片上的人，你认识吗？",
                "source_quote": TEXT,
            }
        ],
        "creative_patterns": ["以照片悬念开场"],
        "uncertainties": ["店主身份待确认"],
    }


class AssetGateway(FakeGateway):
    def structured(self, schema, prompt, **kwargs):
        if schema is ScriptBreakdown:
            output = breakdown()
        elif schema is CharacterProfile:
            output = copy.deepcopy(PROFILE)
        elif issubclass(schema, Production) and "reused_assets" in prompt:
            data = json.loads(prompt[prompt.index('{"outline":') :])
            reused = data["reused_assets"]
            output = {
                "title": "新的调查",
                "script": "小林在旧书店发现新的线索。",
                "shots": [
                    {
                        "id": "NEW_SH_001",
                        "planned_duration_ms": 30000,
                        "shot_size": "中景",
                        "camera": "固定",
                        "action": "小林拿起照片",
                        "dialogue": "",
                        "sound": "环境音",
                        "asset_ids": [x["id"] for x in reused],
                    }
                ],
                "assets": [{**x, "profile": PROFILE} for x in reused],
                "quality_notes": [],
            }
        else:
            return super().structured(schema, prompt, **kwargs)
        output = schema.model_validate(output).model_dump()
        return output, {}, "test-assets-request", "test-only"


def imported(client, monkeypatch):
    monkeypatch.setattr(Workflow, "gateway", property(lambda _: AssetGateway()))
    p = create_project(client)
    script_input = client.post(f"/api/v1/projects/{p}/scripts", json={"title": "旧照片", "text": TEXT}).json()
    job = run_job(
        client,
        client.post(
            f"/api/v1/projects/{p}/script-parse-jobs",
            json=job_body(entity_id=script_input["id"], expected_version=script_input["version"]),
        ),
    )
    project = client.get(f"/api/v1/projects/{p}").json()
    script = next(x for x in project["entities"] if x["id"] == job["result"]["entity_id"])
    role = next(
        x for x in project["entities"] if x["kind"] == "asset" and x["content"]["type"] == "character"
    )
    return p, script, role, script_input


def test_script_assets_profiles_and_view_images(client, monkeypatch):
    p, script, role, _ = imported(client, monkeypatch)
    scene = script["content"]["scenes"][0]
    assert scene["source_start"] == 0 and scene["source_end"] == len(TEXT)
    assert scene["character_ids"] == [role["content"]["id"]]
    assert role["content"]["origin_id"] == script["id"]
    assert role["content"]["profile"]["clothing"] == "蓝色衬衫"
    assert role["content"]["evidence"] == []
    path = f"/api/v1/projects/{p}"
    run_job(
        client,
        client.post(
            path + "/asset-profile-jobs",
            json=job_body(asset_ids=[role["id"]], expected_versions={role["id"]: role["version"]}),
        ),
    )
    role = next(x for x in client.get(path).json()["entities"] if x["id"] == role["id"])
    assert role["version"] == 2 and role["content"]["profile_origin"] == "ai_suggested"
    for view in ["sheet", "portrait"]:
        job = run_job(
            client,
            client.post(
                path + "/asset-image-jobs",
                json=job_body(
                    asset_ids=[role["id"]], expected_versions={role["id"]: role["version"]}, image_view=view
                ),
            ),
        )
        role = next(x for x in client.get(path).json()["entities"] if x["id"] == role["id"])
        assert role["content"]["image_views"][view] == job["result"]["media_id"]
    assert set(role["content"]["image_views"]) == {"sheet", "portrait", "front", "side", "back"}
    result = client.get(path + f"/assets/{role['id']}/images/sheet/download")
    assert result.status_code == 200 and "attachment" in result.headers["content-disposition"]
    assert (
        client.post(
            path + "/asset-image-jobs",
            json=job_body(asset_ids=[role["id"]], expected_versions={role["id"]: 1}),
        ).status_code
        == 409
    )


def test_script_reuse_production_preserves_images_export_and_invalidates(client, monkeypatch):
    p, script, role, source_input = imported(client, monkeypatch)
    path = f"/api/v1/projects/{p}"
    run_job(
        client,
        client.post(
            path + f"/assets/{role['id']}/image-jobs", json=job_body(expected_version=role["version"])
        ),
    )
    role = next(x for x in client.get(path).json()["entities"] if x["id"] == role["id"])
    script = approve(client, p, script)
    response = client.post(
        path + "/adaptations",
        json={
            "source_entity_id": script["id"],
            "expected_source_version": script["version"],
            "brief": {"duration_seconds": 30, "asset_strategy": "reuse", "reuse_asset_ids": [role["id"]]},
        },
    )
    assert response.status_code == 201, response.text
    brief = response.json()
    run_job(client, client.post(f"/api/v1/adaptations/{brief['id']}/outline-jobs", json=job_body()))
    outline = next(x for x in client.get(path).json()["entities"] if x["kind"] == "outline")
    approve(client, p, outline)
    run_job(client, client.post(f"/api/v1/adaptations/{brief['id']}/production-jobs", json=job_body()))
    copied = next(
        x for x in client.get(path).json()["entities"] if x["kind"] == "asset" and x["scope"] == "adaptation"
    )
    assert copied["content"]["id"].startswith("NEW_CHAR_")
    assert copied["content"]["image_views"] == role["content"]["image_views"]
    assert copied["content"]["profile"]["clothing"] == "蓝色衬衫"
    job = run_job(client, client.post(path + "/exports", json=job_body()))
    from backend.config import safe_path

    with zipfile.ZipFile(safe_path(job["result"]["path"])) as archive:
        names = archive.namelist()
        assert any(x.endswith("人物档案.md") for x in names)
        assert any(x.endswith("_sheet.png") for x in names)
        assert any(x.endswith("script_scenes.json") for x in names)
    assert client.post(path + "/scripts", json={"title": "更改", "text": TEXT}).status_code == 409
    assert (
        client.post(
            path + "/scripts",
            json={"title": "更改", "text": TEXT + "灯光熄灭。", "expected_version": source_input["version"]},
        ).status_code
        == 201
    )
    assert (
        next(x for x in client.get(path).json()["entities"] if x["kind"] == "brief")["status"]
        == "needs_update"
    )


def test_script_rejects_fabricated_quotes_and_invalid_links():
    value = breakdown()
    validate_script_breakdown(value, TEXT)
    value["scenes"][0]["source_quote"] = "原文中不存在的句子"
    with pytest.raises(ValueError, match="逐字引用"):
        validate_script_breakdown(value, TEXT)
    value = breakdown()
    value["scenes"][0]["character_ids"] = ["SRC_SCENE_001"]
    with pytest.raises(ValueError, match="类型不匹配"):
        validate_script_breakdown(value, TEXT)


def test_document_import_and_foreign_image_guard(client):
    assert script_file_text("剧本.txt", TEXT.encode("gb18030")) == TEXT
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{TEXT}</w:t></w:r></w:p></w:body></w:document>',
        )
    assert script_file_text("剧本.docx", out.getvalue()) == TEXT
    with pytest.raises(ValueError, match="支持"):
        script_file_text("x.pdf", b"no")
    p = create_project(client)
    path = f"/api/v1/projects/{p}"
    assert client.post(path + "/script-files", files={"file": ("x.docx", b"corrupt")}).status_code == 422
    asset = client.post(
        path + "/assets",
        json={"scope": "source", "type": "character", "name": "人物", "description": "手动人物档案"},
    ).json()
    content = {**asset["content"], "image_views": {"sheet": "foreign-media"}}
    assert (
        client.patch(
            path + f"/assets/{asset['id']}", json={"expected_version": 1, "content": content}
        ).status_code
        == 422
    )


def test_script_merge_updates_scene_references(client, monkeypatch):
    p, script, role, _ = imported(client, monkeypatch)
    path = f"/api/v1/projects/{p}"
    other = client.post(
        path + "/assets",
        json={"scope": "source", "type": "character", "name": "保留人物", "description": "手动设定"},
    ).json()
    result = client.post(
        path + "/asset-merges",
        json={"source_id": role["id"], "target_id": other["id"], "source_version": 1, "target_version": 1},
    )
    assert result.status_code == 200, result.text
    with Session() as db:
        current = db.get(Entity, script["id"])
        assert current.content["scenes"][0]["character_ids"] == [other["content"]["id"]]


def test_script_reordering_keeps_character_identity_and_images(client, monkeypatch):
    p, script, role, source_input = imported(client, monkeypatch)
    path = f"/api/v1/projects/{p}"
    run_job(
        client,
        client.post(
            path + f"/assets/{role['id']}/image-jobs", json=job_body(expected_version=role["version"])
        ),
    )
    before = next(x for x in client.get(path).json()["entities"] if x["id"] == role["id"])
    edited = client.post(
        path + "/scripts",
        json={
            "title": "旧照片第二稿",
            "text": TEXT + "灯光熄灭。",
            "expected_version": source_input["version"],
        },
    ).json()

    class Reordered(AssetGateway):
        def structured(self, schema, prompt, **kwargs):
            output, usage, request_id, model = super().structured(schema, prompt, **kwargs)
            output["assets"].reverse()
            return output, usage, request_id, model

    monkeypatch.setattr(Workflow, "gateway", property(lambda _: Reordered()))
    run_job(
        client,
        client.post(
            path + "/script-parse-jobs",
            json=job_body(entity_id=edited["id"], expected_version=edited["version"]),
        ),
    )
    after = next(x for x in client.get(path).json()["entities"] if x["id"] == role["id"])
    assert after["content"]["image_views"] == before["content"]["image_views"]
    assert after["content"]["name"] == "小林"
    assert not after["content"]["retired"]


def test_character_sheet_contains_portrait_front_side_and_back(tmp_path):
    from PIL import Image

    colors = {"portrait": "red", "front": "green", "side": "blue", "back": "yellow"}
    paths = {}
    for key, color in colors.items():
        paths[key] = tmp_path / f"{key}.png"
        Image.new("RGB", (200, 200), color).save(paths[key])
    target = tmp_path / "sheet.png"
    compose_character_sheet(paths, target)
    with Image.open(target) as sheet:
        assert sheet.size == (2048, 1024)
        assert [sheet.getpixel((x, 512)) for x in [320, 874, 1343, 1813]] == [
            (255, 0, 0),
            (0, 128, 0),
            (0, 0, 255),
            (255, 255, 0),
        ]

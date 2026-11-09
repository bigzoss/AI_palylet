import base64
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

from PIL import Image

from backend.config import safe_path
from backend.db import Entity, Job, Session
from backend.schemas import AnalysisBatch, Brief, Outline, Production, StoryPattern
from backend.services import media, store
from backend.services.asset_library import PROFILE_LABELS
from backend.workflows import Workflow
from worker.main import claim, execute, recover


def create_project(client):
    return client.post("/api/v1/projects", json={"name": "测试工程"}).json()["id"]


def job_body(**extra):
    from uuid import uuid4

    return {"idempotency_key": uuid4().hex, **extra}


def run_job(client, result):
    assert result.status_code == 202, result.text
    job_id = result.json()["id"]
    assert claim() == job_id
    execute(job_id)
    result = client.get(f"/api/v1/jobs/{job_id}").json()
    assert result["status"] == "succeeded", result
    return result


def approve(client, p, obj):
    result = client.post(
        f"/api/v1/projects/{p}/reviews",
        json={"entity_id": obj["id"], "expected_version": obj["version"], "status": "approved"},
    )
    assert result.status_code == 200, result.text
    return result.json()


class FakeGateway:
    """Deterministic provider for tests only; never imported by production code."""

    calls = 0

    def structured(self, schema, prompt, **kwargs):
        self.calls += 1
        if schema is AnalysisBatch:
            batch = json.loads(prompt[prompt.index('{"shots":') :])["shots"]
            output = {
                "shots": [
                    {
                        **{k: s[k] for k in ["id", "start_ms", "end_ms"]},
                        "shot_size": "中景",
                        "camera": "固定",
                        "action": "测试画面",
                        "dialogue": "",
                        "asset_ids": ["SRC_CHAR_001"],
                        "uncertainty": "合成测试画面，无真人",
                    }
                    for s in batch
                ],
                "assets": [
                    {
                        "id": "SRC_CHAR_001",
                        "type": "character",
                        "name": "测试人物",
                        "description": "测试样例",
                        "prompt": "测试",
                        "evidence": [
                            {
                                "shot_id": batch[0]["id"],
                                "timestamp_ms": batch[0]["frames"][0]["timestamp_ms"],
                                "basis": "visual",
                                "note": "仅测试",
                            }
                        ],
                    }
                ],
            }
        elif schema is StoryPattern:
            output = {
                "synopsis": "测试故事",
                "hook": "测试钩子",
                "conflict": "测试冲突",
                "escalation": ["测试"],
                "reversal": "测试反转",
                "ending": "测试结局",
                "reusable_patterns": ["测试规律"],
            }
        elif schema is Outline:
            output = {
                "title": "新故事",
                "logline": "全新事件",
                "characters": ["林晚"],
                "beats": ["开端", "转折", "结局"],
                "ending": "解决冲突",
                "changes_from_source": ["新人物与事件"],
            }
        elif issubclass(schema, Production):
            output = {
                "title": "新故事",
                "script": "# 新故事\n\n剧本测试",
                "shots": [
                    {
                        "id": "NEW_SH_001",
                        "planned_duration_ms": 30000,
                        "shot_size": "中景",
                        "camera": "固定",
                        "action": "林晚接听电话",
                        "dialogue": "我来处理。",
                        "sound": "环境音",
                        "asset_ids": ["NEW_CHAR_001"],
                    }
                ],
                "assets": [
                    {
                        "id": "NEW_CHAR_001",
                        "type": "character",
                        "name": "林晚",
                        "description": "新角色",
                        "profile": {key: "未知" for key in PROFILE_LABELS},
                        "prompt": "肖像与正侧背全身形象卡",
                        "evidence": [],
                    }
                ],
                "quality_notes": ["测试产物"],
            }
        else:
            raise AssertionError(schema)
        schema.model_validate(output)
        return output, {"input_tokens": 10, "output_tokens": 10}, "test-request", "test-only"

    def image(self, *_):
        out = io.BytesIO()
        Image.new("RGB", (100, 100), "#7866ab").save(out, format="PNG")
        return {"base64": base64.b64encode(out.getvalue()).decode()}, None, "test-image", "test-only"


def test_full_workflow_media_versions_export(client, monkeypatch):
    p = create_project(client)
    source = safe_path("synthetic.mp4")
    media.command(
        [
            media.ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=purple:s=180x320:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ]
    )
    with source.open("rb") as file:
        response = client.post(
            f"/api/v1/projects/{p}/media", files={"file": ("sample.mp4", file, "video/mp4")}
        )
    assert response.status_code == 201, response.text
    uploaded = response.json()
    assert uploaded["info"]["duration_ms"] == 2000
    assert not uploaded["info"]["has_audio"]
    fake = FakeGateway()
    monkeypatch.setattr(Workflow, "gateway", property(lambda _: fake))
    body = job_body(media_id=uploaded["id"])
    result = client.post(f"/api/v1/projects/{p}/analysis-jobs", json=body)
    duplicate = client.post(f"/api/v1/projects/{p}/analysis-jobs", json=body)
    assert result.json()["id"] == duplicate.json()["id"]
    run_job(client, result)
    source_analysis = client.get(f"/api/v1/projects/{p}/analysis").json()
    assert source_analysis["content"]["shots"][0]["frame_media_ids"]
    preview = source_analysis["content"]["preview_media_id"]
    ranged = client.get(f"/api/v1/media/{preview}/content", headers={"Range": "bytes=0-31"})
    assert ranged.status_code == 206
    assert len(ranged.content) == 32
    source_analysis = approve(client, p, source_analysis)
    brief_response = client.post(
        f"/api/v1/projects/{p}/adaptations",
        json={
            "brief": Brief(duration_seconds=30).model_dump(),
            "expected_source_version": source_analysis["version"],
        },
    )
    assert brief_response.status_code == 201, brief_response.text
    brief = brief_response.json()
    run_job(client, client.post(f"/api/v1/adaptations/{brief['id']}/outline-jobs", json=job_body()))
    detail = client.get(f"/api/v1/projects/{p}").json()
    outline = approve(client, p, next(e for e in detail["entities"] if e["kind"] == "outline"))
    run_job(client, client.post(f"/api/v1/adaptations/{brief['id']}/production-jobs", json=job_body()))
    detail = client.get(f"/api/v1/projects/{p}").json()
    asset = next(e for e in detail["entities"] if e["kind"] == "asset" and e["scope"] == "adaptation")
    run_job(
        client,
        client.post(
            f"/api/v1/projects/{p}/assets/{asset['id']}/image-jobs",
            json=job_body(expected_version=asset["version"]),
        ),
    )
    assets = client.get(f"/api/v1/projects/{p}/assets?scope=adaptation").json()
    assert assets[0]["version"] == 2 and assets[0]["content"]["image_ids"]
    # Old editor cannot overwrite a generated image.
    stale = client.patch(
        f"/api/v1/projects/{p}/assets/{asset['id']}",
        json={"expected_version": 1, "content": asset["content"]},
    )
    assert stale.status_code == 409
    result = run_job(client, client.post(f"/api/v1/projects/{p}/exports", json=job_body()))
    downloaded = client.get(f"/api/v1/exports/{result['id']}/download")
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["draft"] is True
        assert "adaptation/script.md" in archive.namelist()
        assert any(x.endswith(".png") for x in archive.namelist())
        assert not any(".env" in x or x.endswith(".mp4") for x in archive.namelist())
        import hashlib

        for entry in manifest["files"]:
            assert hashlib.sha256(archive.read(entry["path"])).hexdigest() == entry["sha256"]
    # Changing outline invalidates production and asset approvals.
    response = client.patch(
        f"/api/v1/projects/{p}/entities/{outline['id']}",
        json={"expected_version": outline["version"], "content": {**outline["content"], "title": "修订标题"}},
    )
    assert response.status_code == 200
    detail = client.get(f"/api/v1/projects/{p}").json()
    assert next(e for e in detail["entities"] if e["kind"] == "production")["status"] == "needs_update"


def test_cancel_recovery_and_checkpoints(client):
    p = create_project(client)
    with Session() as db:
        job = Job(project_id=p, kind="export", idempotency_key="cancel-test", payload={})
        db.add(job)
        db.commit()
        job_id = job.id
    assert client.post(f"/api/v1/jobs/{job_id}/cancel").json()["status"] == "cancelled"
    assert claim() is None
    with Session() as db:
        job = Job(
            project_id=p,
            kind="export",
            idempotency_key="recovery-test",
            payload={},
            status="running",
            heartbeat=(datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(),
        )
        db.add(job)
        db.commit()
        other_id = job.id
    recover()
    assert client.get(f"/api/v1/jobs/{other_id}").json()["error_code"] == "WORKER_INTERRUPTED"
    with Session() as db:
        job = Job(project_id=p, kind="export", idempotency_key="cache-test", payload={}, status="running")
        db.add(job)
        db.commit()
        cache_id = job.id
    workflow = Workflow(cache_id)
    calls = []

    def fn():
        calls.append(1)
        return {"ok": True}, None, None, None

    assert workflow.step("unit-stage", 10, {"v": 1}, fn) == {"ok": True}
    assert workflow.step("unit-stage", 10, {"v": 1}, fn) == {"ok": True}
    assert len(calls) == 1


def test_entity_conflicts_scope_and_unknown_routes(client):
    p, other = create_project(client), create_project(client)
    with Session() as db:
        obj = store.save(
            db,
            p,
            "asset",
            "source",
            {
                "id": "SRC_CHAR_001",
                "type": "character",
                "name": "A",
                "description": "A",
                "prompt": "",
                "evidence": [],
                "image_ids": [],
            },
        )
        db.commit()
        entity_id = obj.id
    assert client.get(f"/api/v1/projects/{other}/entities/{entity_id}/revisions").status_code == 404
    assert client.get("/api/v1/missing").status_code == 404
    assert client.post("/api/v1/projects", json={"name": "   "}).status_code == 422
    assert (
        client.post(f"/api/v1/projects/{p}/media", files={"file": ("bad.mp4", b"not video")}).status_code
        == 422
    )
    with Session() as db:
        obj = db.get(Entity, entity_id)
        updated = store.save(db, p, "asset", "source", obj.content, entity_id=obj.id, expected=1)
        db.commit()
        assert updated.version == 2
    stale = client.post(
        f"/api/v1/projects/{p}/reviews",
        json={"entity_id": entity_id, "expected_version": 1, "status": "approved"},
    )
    assert stale.status_code == 409


def test_srt_and_safe_path():
    text = "1\n00:00:00,100 --> 00:00:01,500\n你好\n\n2\n00:00:01,500 --> 00:00:02,000\n再见"
    values = media.parse_srt(text, 2000)
    assert values[0]["start_ms"] == 100 and values[1]["end_ms"] == 2000
    import pytest

    with pytest.raises(ValueError):
        safe_path("../outside.env")
    with pytest.raises(ValueError):
        media.parse_srt("invalid", 2000)


def test_merge_and_split_keep_references_and_history(client):
    p = create_project(client)
    with Session() as db:
        ids = []
        for n in [1, 2]:
            asset = store.save(
                db,
                p,
                "asset",
                "source",
                {
                    "id": f"SRC_CHAR_00{n}",
                    "name": f"人物{n}",
                    "type": "character",
                    "description": "参考",
                    "prompt": "",
                    "image_ids": [],
                    "evidence": [
                        {
                            "shot_id": f"SRC_SH_00{n}",
                            "timestamp_ms": n * 100,
                            "basis": "visual",
                            "note": "测试",
                        }
                    ],
                },
            )
            ids.append(asset.id)
        store.save(
            db,
            p,
            "analysis",
            "source",
            {"shots": [{"id": f"SRC_SH_00{n}", "asset_ids": [f"SRC_CHAR_00{n}"]} for n in [1, 2]]},
        )
        db.commit()
    merged = client.post(
        f"/api/v1/projects/{p}/asset-merges",
        json={
            "source_id": ids[0],
            "target_id": ids[1],
            "source_version": 1,
            "target_version": 1,
        },
    )
    assert merged.status_code == 200, merged.text
    analysis = client.get(f"/api/v1/projects/{p}/analysis").json()
    assert all(s["asset_ids"] == ["SRC_CHAR_002"] for s in analysis["content"]["shots"])
    split = client.post(
        f"/api/v1/projects/{p}/assets/{ids[1]}/split",
        json={
            "expected_version": 2,
            "name": "独立人物",
            "shot_ids": ["SRC_SH_001"],
        },
    )
    assert split.status_code == 201, split.text
    created = split.json()
    assert created["content"]["evidence"][0]["shot_id"] == "SRC_SH_001"
    analysis = client.get(f"/api/v1/projects/{p}/analysis").json()
    assert analysis["content"]["shots"][0]["asset_ids"] == [created["content"]["id"]]
    assert analysis["content"]["shots"][1]["asset_ids"] == ["SRC_CHAR_002"]
    revisions = client.get(f"/api/v1/projects/{p}/entities/{ids[1]}/revisions").json()
    assert [r["version"] for r in revisions] == [3, 2, 1]


def test_missing_key_fails_without_fabricated_results(client):
    import pytest

    from backend.services.gateway import ConfigurationError, Gateway

    with pytest.raises(ConfigurationError):
        Gateway()
    p = create_project(client)
    with Session() as db:
        job = Job(
            project_id=p, kind="outline", idempotency_key="missing-key", payload={"brief": {}, "source": {}}
        )
        db.add(job)
        db.commit()
        job_id = job.id
    assert claim() == job_id
    execute(job_id)
    result = client.get(f"/api/v1/jobs/{job_id}").json()
    assert result["status"] == "failed" and result["error_code"] == "CONFIGURATION"
    assert client.get(f"/api/v1/projects/{p}").json()["entities"] == []

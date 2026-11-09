import base64
import json

import httpx
import pytest
from openai import OpenAI
from PIL import Image
from pydantic import BaseModel

from backend.config import Settings, safe_path
from backend.services import gateway as module


class Probe(BaseModel):
    answer: str


def test_export_style_config_and_ustc_defaults(tmp_path, monkeypatch):
    for name in [
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_TEXT_MODEL",
        "OPENAI_VISION_MODEL",
        "OPENAI_IMAGE_MODEL",
        "OPENAI_TRANSCRIBE_MODEL",
        "TEACHER_MODEL",
        "OPENAI_API_MODE",
    ]:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env copy.example"
    path.write_text(
        "export OPENAI_API_BASE=https://api.llm.ustc.edu.cn/v1\nexport TEACHER_MODEL=qwen3.8-flash-next\n",
        encoding="utf-8",
    )
    cfg = Settings(_env_file=path)
    assert cfg.api_mode == "chat_completions"
    assert cfg.openai_text_model == cfg.openai_vision_model == "qwen3.8-flash-next"
    assert cfg.openai_image_model == "qwen-image-2.1"
    assert cfg.openai_transcribe_model == ""
    assert cfg.image_size == "1024x1024"
    monkeypatch.setenv("OPENAI_TEXT_MODEL", "another-text-model")
    monkeypatch.setenv("OPENAI_VISION_MODEL", "explicit-vision-model")
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "")
    cfg = Settings(_env_file=path)
    assert cfg.openai_text_model == "another-text-model"
    assert cfg.openai_vision_model == "explicit-vision-model"
    assert cfg.openai_image_model == ""


def configured(monkeypatch, mode="chat_completions"):
    cfg = Settings(
        _env_file=None,
        openai_api_key="test-only",
        openai_base_url="https://provider.example/v1",
        openai_api_mode=mode,
        openai_text_model="text-test",
        openai_vision_model="vision-test",
        openai_image_model="image-test",
        openai_transcribe_model="",
        openai_image_size="1024x1024",
    )
    monkeypatch.setattr(module, "settings", cfg)
    return cfg


def gateway_with_transport(cfg, fn):
    gateway = module.Gateway()
    gateway.client.close()
    gateway.client = OpenAI(
        api_key="test-only",
        base_url=cfg.openai_base_url,
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(fn)),
    )
    return gateway


def test_chat_completions_uses_custom_host_and_correct_image_schema(monkeypatch):
    cfg = configured(monkeypatch)
    path = safe_path("test-provider/frame.jpg")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), "red").save(path)

    def handler(request):
        assert str(request.url) == "https://provider.example/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "vision-test"
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["strict"] is True
        content = payload["messages"][1]["content"]
        assert content[-1]["type"] == "image_url"
        assert content[-1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert "input_image" not in str(content)
        return httpx.Response(
            200,
            json={
                "id": "chat-test",
                "object": "chat.completion",
                "created": 1,
                "model": "vision-test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"answer":"ready"}'},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    gateway = gateway_with_transport(cfg, handler)
    result, usage, request_id, model = gateway.structured(
        Probe,
        "test",
        vision=True,
        images=[{"path": "test-provider/frame.jpg", "timestamp_ms": 1000, "shot_id": "SRC_SH_001"}],
    )
    assert result == {"answer": "ready"} and usage["total_tokens"] == 15
    assert request_id == "chat-test" and model == "vision-test"


def test_responses_mode_remains_supported(monkeypatch):
    cfg = configured(monkeypatch, "responses")

    def handler(request):
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        assert payload["text"]["format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "id": "resp-test",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "text-test",
                "output": [
                    {
                        "id": "msg-test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": '{"answer":"ready"}', "annotations": []}],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            },
        )

    gateway = gateway_with_transport(cfg, handler)
    assert gateway.structured(Probe, "test")[0] == {"answer": "ready"}


def test_ustc_qwen_thinking_defaults_and_explicit_override(monkeypatch):
    cfg = configured(monkeypatch)
    cfg.openai_base_url = "https://api.llm.ustc.edu.cn/v1"
    cfg.openai_text_model = "qwen3.8-flash-next"
    expected = [False, True, True]

    def handler(request):
        payload = json.loads(request.content)
        assert payload["chat_template_kwargs"]["enable_thinking"] is expected.pop(0)
        return httpx.Response(
            200,
            json={
                "id": "chat-test",
                "object": "chat.completion",
                "created": 1,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"answer":"ready"}'},
                    }
                ],
            },
        )

    gateway = gateway_with_transport(cfg, handler)
    gateway.structured(Probe, "test")
    cfg.openai_enable_thinking = True
    gateway.structured(Probe, "test")
    cfg.openai_enable_thinking = None
    cfg.openai_text_model = "qwen3.8-reasoner"
    gateway.structured(Probe, "test")
    assert expected == []


def test_image_generation_and_edit_honor_provider_parameters(monkeypatch):
    cfg = configured(monkeypatch)
    calls = []
    path = safe_path("test-provider/reference.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), "blue").save(path)

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/generations"):
            payload = json.loads(request.content)
            assert payload["size"] == "1024x1024" and payload["response_format"] == "b64_json"
        else:
            assert b'name="response_format"' in request.content
            assert b"b64_json" in request.content and b"1024x1024" in request.content
        return httpx.Response(
            200, json={"created": 1, "data": [{"b64_json": base64.b64encode(path.read_bytes()).decode()}]}
        )

    gateway = gateway_with_transport(cfg, handler)
    assert gateway.image("test")[0]["base64"]
    assert gateway.image("test", "test-provider/reference.png")[0]["base64"]
    assert calls == ["/v1/images/generations", "/v1/images/edits"]
    with pytest.raises(module.ConfigurationError, match="转写"):
        gateway.transcribe("unused.mp3")


def test_image_rate_limit_retry_reopens_reference_stream(monkeypatch):
    cfg = configured(monkeypatch)
    cfg.openai_image_interval_seconds = 0
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    path = safe_path("test-provider/retry.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), "green").save(path)
    requests = []

    def handler(request):
        requests.append(request)
        assert path.read_bytes() in request.content
        if len(requests) == 1:
            return httpx.Response(
                429,
                json={
                    "error": {
                        "message": "slow down",
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded",
                    }
                },
            )
        return httpx.Response(
            200, json={"created": 1, "data": [{"b64_json": base64.b64encode(path.read_bytes()).decode()}]}
        )

    assert gateway_with_transport(cfg, handler).image("背面全身", "test-provider/retry.png")[0]["base64"]
    assert len(requests) == 2


def test_no_transcription_provider_uses_explicit_visible_subtitle_fallback(client, monkeypatch):
    import backend.workflows as workflows
    from backend.db import Job, Media, Session
    from backend.schemas import AnalysisBatch, StoryPattern
    from backend.workflows import Workflow
    from worker.main import claim, execute

    monkeypatch.setattr(workflows.settings, "openai_transcribe_model", "")
    p = client.post("/api/v1/projects", json={"name": "字幕回退测试"}).json()["id"]
    with Session() as db:
        record = Media(
            project_id=p,
            kind="video",
            path="synthetic.mp4",
            name="synthetic",
            sha256="test",
            info={"duration_ms": 1000, "has_audio": True},
        )
        db.add(record)
        db.flush()
        job = Job(
            project_id=p,
            kind="analysis",
            idempotency_key="fallback-test",
            payload={"media_id": record.id, "input_versions": {}},
        )
        db.add(job)
        db.commit()
        job_id = job.id

    class Fake:
        def structured(self, schema, prompt, **kwargs):
            if schema is AnalysisBatch:
                assert "没有语音转写" in prompt
                result = {
                    "shots": [
                        {
                            "id": "SRC_SH_001",
                            "start_ms": 0,
                            "end_ms": 1000,
                            "shot_size": "中景",
                            "camera": "固定",
                            "action": "测试",
                            "dialogue": "",
                            "asset_ids": [],
                            "uncertainty": "仅关键帧字幕",
                        }
                    ],
                    "assets": [],
                }
            else:
                assert schema is StoryPattern
                result = {
                    "synopsis": "测试",
                    "hook": "未知",
                    "conflict": "未知",
                    "escalation": [],
                    "reversal": "未知",
                    "ending": "未知",
                    "reusable_patterns": [],
                }
            return result, None, "test", "test"

        def transcribe(self, *_):
            raise AssertionError("Must never call an unavailable transcription endpoint")

    monkeypatch.setattr(Workflow, "gateway", property(lambda _: Fake()))
    monkeypatch.setattr(
        workflows.media,
        "prepare",
        lambda *_: {
            "shots": [{"id": "SRC_SH_001", "start_ms": 0, "end_ms": 1000, "frames": []}],
            "preview_media_id": "test",
            "audio_path": "synthetic.mp3",
        },
    )
    assert claim() == job_id
    execute(job_id)
    result = client.get(f"/api/v1/jobs/{job_id}").json()
    assert result["status"] == "succeeded", result
    analysis = client.get(f"/api/v1/projects/{p}/analysis").json()
    assert analysis["content"]["transcript"]["mode"] == "visual_subtitles_only"
    assert "SRT" in analysis["content"]["transcript"]["note"]


def test_validation_repair_is_bounded_and_valid_checkpoint_is_reused(client, monkeypatch):
    from sqlalchemy import select

    from backend.db import Job, Session, StageRun
    from backend.workflows import Workflow

    p = client.post("/api/v1/projects", json={"name": "格式修复测试"}).json()["id"]
    with Session() as db:
        job = Job(project_id=p, kind="outline", payload={}, idempotency_key="repair-test", status="running")
        db.add(job)
        db.commit()
        job_id = job.id

    class Fake:
        calls = 0

        def structured(self, *args, **kwargs):
            self.calls += 1
            return (
                {"answer": "bad" if self.calls == 1 else "ready"},
                {"total_tokens": 3},
                "test-request",
                "fake",
            )

    fake = Fake()
    monkeypatch.setattr(Workflow, "gateway", property(lambda _: fake))
    workflow = Workflow(job_id)

    def validate(value):
        if value["answer"] != "ready":
            raise ValueError("not ready")

    for _ in range(2):
        assert workflow.model_step("repair", 20, Probe, "return ready", model="fake", validate=validate) == {
            "answer": "ready"
        }
    assert fake.calls == 2
    with Session() as db:
        runs = db.scalars(select(StageRun).where(StageRun.job_id == job_id)).all()
        assert [r.status for r in runs].count("failed") == 1
        assert len([r for r in runs if r.request_id]) == 2

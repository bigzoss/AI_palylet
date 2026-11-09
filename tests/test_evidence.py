import copy

import pytest
from sqlalchemy import select

from backend.db import Job, Session, StageRun
from backend.workflows import Workflow, merge_evidence, validate_batch


@pytest.fixture
def batch_case():
    past = {"shot_id": "SRC_SH_003", "timestamp_ms": 9083, "basis": "visual", "note": "已校验参考帧"}
    present = {"shot_id": "SRC_SH_007", "timestamp_ms": 17466, "basis": "visual", "note": "当前参考帧"}
    asset = {"id": "SRC_CHAR_001", "type": "character", "evidence": [past]}
    known = {asset["id"]: copy.deepcopy(asset)}
    asset["evidence"] = [dict(past, note="模型重复带回的历史说明"), present]
    batch = [{"id": "SRC_SH_007", "start_ms": 15800, "end_ms": 19133, "frames": [{"timestamp_ms": 17466}]}]
    output = {
        "shots": [{"id": "SRC_SH_007", "start_ms": 15800, "end_ms": 19133, "asset_ids": [asset["id"]]}],
        "assets": [asset],
    }
    return output, batch, known


def test_verified_same_asset_history_is_valid_and_deduplicated(batch_case):
    output, batch, known = batch_case
    validate_batch(output, batch, known)
    combined = merge_evidence(known["SRC_CHAR_001"]["evidence"], output["assets"][0]["evidence"])
    assert len(combined) == 2
    assert combined[0]["note"] == "已校验参考帧"


@pytest.mark.parametrize("alteration", ["unknown_shot", "wrong_time", "wrong_basis", "different_asset"])
def test_unverified_history_is_still_rejected(batch_case, alteration):
    output, batch, known = batch_case
    evidence = output["assets"][0]["evidence"][0]
    if alteration == "unknown_shot":
        evidence["shot_id"] = "SRC_SH_999"
    elif alteration == "wrong_time":
        evidence["timestamp_ms"] += 1
    elif alteration == "wrong_basis":
        evidence["basis"] = "inferred"
    else:
        output["assets"][0]["id"] = "SRC_CHAR_002"
        output["shots"][0]["asset_ids"] = ["SRC_CHAR_002"]
    with pytest.raises(ValueError, match="历史证据"):
        validate_batch(output, batch, known)


def test_current_batch_time_and_frame_checks_are_preserved(batch_case):
    output, batch, known = batch_case
    output["assets"][0]["evidence"][1]["timestamp_ms"] = 19133
    with pytest.raises(ValueError, match="超出范围"):
        validate_batch(output, batch, known)
    output["assets"][0]["evidence"][1]["timestamp_ms"] = 17000
    with pytest.raises(ValueError, match="实际参考帧"):
        validate_batch(output, batch, known)


def test_exact_failed_checkpoint_can_be_revalidated_without_an_api_call(client):
    p = client.post("/api/v1/projects", json={"name": "历史引用检查点"}).json()["id"]
    with Session() as db:
        job = Job(
            project_id=p, kind="analysis", status="running", idempotency_key="evidence-revalidate", payload={}
        )
        db.add(job)
        db.commit()
        jid = job.id
    workflow = Workflow(jid)
    cache_key = workflow.cache_key("同一输入的镜头分析", {"input": 1}, "test-model")
    with Session() as db:
        db.add(
            StageRun(
                job_id=jid,
                project_id=p,
                cache_key=cache_key,
                stage="同一输入的镜头分析",
                status="failed",
                output={"verified": True},
                model="test-model",
                usage={"total_tokens": 5},
            )
        )
        db.commit()

    def validate(value):
        assert value["verified"] is True

    def must_not_request():
        raise AssertionError("Already-valid model output must not be requested again")

    assert workflow.step(
        "同一输入的镜头分析", 35, {"input": 1}, must_not_request, model="test-model", validate=validate
    ) == {"verified": True}
    with Session() as db:
        rows = db.scalars(select(StageRun).where(StageRun.job_id == jid)).all()
        assert len(rows) == 1 and rows[0].status == "succeeded"
        assert "复核通过" in rows[0].stage

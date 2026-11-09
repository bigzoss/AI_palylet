import hashlib
import time

from sqlalchemy import select

from .config import safe_path, settings
from .db import Entity, Job, Media, Session, StageRun, clone, now, serialize
from .schemas import AnalysisBatch, Outline, StoryPattern, validate_production
from .services import media, store
from .services.export import build_export
from .services.gateway import PROMPT_VERSION, Gateway, prompt_json


class Cancelled(Exception):
    pass


def evidence_key(value):
    return value["shot_id"], value["timestamp_ms"], value["basis"]


def merge_evidence(previous, current):
    # Keep the original verified note when the model echoes a historical reference.
    merged = {}
    for evidence in [*previous, *current]:
        merged.setdefault(evidence_key(evidence), evidence)
    return list(merged.values())


def validate_batch(output, batch, known):
    expected = {s["id"]: s for s in batch}
    if len(output["shots"]) != len(batch) or {s["id"] for s in output["shots"]} != set(expected):
        raise ValueError("模型镜头编号与输入不一致")
    for shot in output["shots"]:
        ref = expected[shot["id"]]
        if (shot["start_ms"], shot["end_ms"]) != (ref["start_ms"], ref["end_ms"]):
            raise ValueError("模型改写了镜头时间范围")
    ids = set(known)
    if len({a["id"] for a in output["assets"]}) != len(output["assets"]):
        raise ValueError("同一批次的资产 ID 重复")
    for asset in output["assets"]:
        if not asset["id"].startswith("SRC_"):
            raise ValueError("原片资产 ID 无效")
        ids.add(asset["id"])
        if asset["id"] in known and known[asset["id"]]["type"] != asset["type"]:
            raise ValueError("资产 ID 的类型在跨批次分析中发生变化")
        for evidence in asset["evidence"]:
            ref = expected.get(evidence["shot_id"])
            if not ref:
                verified = {evidence_key(e) for e in known.get(asset["id"], {}).get("evidence", [])}
                if evidence_key(evidence) in verified:
                    # An exact reference already validated for this SAME asset in an earlier batch.
                    continue
                raise ValueError(
                    f"资产 {asset['id']} 引用了未校验的镜头 {evidence['shot_id']}，不能作为历史证据"
                )
            if not ref["start_ms"] <= evidence["timestamp_ms"] < ref["end_ms"]:
                raise ValueError(
                    f"镜头 {evidence['shot_id']} 的证据时间 {evidence['timestamp_ms']}ms 超出范围 [{ref['start_ms']}, {ref['end_ms']})ms"
                )
            if evidence["basis"] == "visual" and evidence["timestamp_ms"] not in {
                f["timestamp_ms"] for f in ref["frames"]
            }:
                raise ValueError("视觉证据未指向提供的实际参考帧")
    if any(not set(shot["asset_ids"]).issubset(ids) for shot in output["shots"]):
        raise ValueError("原片分镜存在无效资产引用")


class Workflow:
    def __init__(self, job_id):
        self.job_id = job_id
        with Session() as db:
            job = db.get(Job, job_id)
            self.project_id, self.payload, self.kind = job.project_id, job.payload, job.kind
        self._gateway = None

    @property
    def gateway(self):
        if self._gateway is None:
            self._gateway = Gateway()
        return self._gateway

    def check(self):
        with Session() as db:
            job = db.get(Job, self.job_id)
            if job.status == "cancel_requested":
                raise Cancelled()

    def cache_key(self, name, inputs, model):
        return hashlib.sha256(
            prompt_json(
                [
                    name,
                    inputs,
                    model,
                    settings.openai_base_url,
                    settings.api_mode,
                    settings.image_size,
                    settings.openai_enable_thinking,
                    PROMPT_VERSION,
                ]
            ).encode()
        ).hexdigest()

    def model_step(self, name, progress, schema, prompt, *, model, images=None, vision=False, validate=None):
        try:
            return self.step(
                name,
                progress,
                prompt,
                lambda: self.gateway.structured(schema, prompt, images=images, vision=vision),
                model=model,
                validate=validate,
            )
        except ValueError as exc:
            # One bounded repair, logged separately; never loosen evidence or business validation.
            with Session() as db:
                last = db.scalar(
                    select(StageRun)
                    .where(StageRun.job_id == self.job_id, StageRun.stage == name)
                    .order_by(StageRun.created_at.desc())
                )
                invalid_output = last.output if last else None
            repair_prompt = (
                prompt
                + "\n上一次输出未通过校验。仅纠正以下错误，不编造证据、不修改原始时间："
                + str(exc)[:1500]
                + "\n视觉证据的 timestamp_ms 必须等于提供的实际帧时间。"
                "只有对白提及或推测存在的角色、场景、道具，basis 用 dialogue 或 inferred，不能标为 visual。"
                "如证据无法确认，可留空 evidence。分镜与资产ID必须与输入或本次计划对应。"
                "\n待纠正输出：" + prompt_json(invalid_output)
            )
            corrected = self.step(
                name + "（格式修复）",
                progress,
                repair_prompt,
                lambda: self.gateway.structured(schema, repair_prompt, images=images, vision=vision),
                model=model,
                validate=validate,
            )
            with Session() as db:
                db.add(
                    StageRun(
                        job_id=self.job_id,
                        project_id=self.project_id,
                        stage=name + "（修复后检查点）",
                        cache_key=self.cache_key(name, prompt, model),
                        status="succeeded",
                        output=clone(corrected),
                        elapsed_ms=0,
                    )
                )
                db.commit()
            return corrected

    def step(self, name, progress, inputs, fn, *, model=None, validate=None):
        self.check()
        key = self.cache_key(name, inputs, model)
        with Session() as db:
            job = db.get(Job, self.job_id)
            job.stage, job.progress, job.updated_at = name, progress, now()
            cached = db.scalar(
                select(StageRun)
                .where(
                    StageRun.project_id == self.project_id,
                    StageRun.cache_key == key,
                    StageRun.status.in_(["succeeded", "failed"] if validate else ["succeeded"]),
                    StageRun.output.is_not(None),
                )
                .order_by((StageRun.status == "succeeded").desc(), StageRun.created_at.desc())
            )
            db.commit()
            if cached:
                try:
                    if validate:
                        validate(cached.output)
                except ValueError:
                    cached.status = "failed"
                    db.commit()
                else:
                    if cached.status == "failed":
                        cached.status = "succeeded"
                        cached.stage += "（校验修复后复核通过）"
                        db.commit()
                    return clone(cached.output)
            run = StageRun(
                job_id=self.job_id,
                project_id=self.project_id,
                cache_key=key,
                stage=name,
                model=model,
                status="running",
            )
            db.add(run)
            db.commit()
            run_id = run.id
        start = time.monotonic()
        received = False
        try:
            output, usage, request_id, actual_model = fn()
            received = True
            if hasattr(usage, "model_dump"):
                usage = usage.model_dump()
            with Session() as db:
                run = db.get(StageRun, run_id)
                run.status, run.output, run.usage, run.request_id = "received", output, usage, request_id
                run.model, run.elapsed_ms = actual_model, round((time.monotonic() - start) * 1000)
                db.commit()
            if validate:
                validate(output)
            with Session() as db:
                run = db.get(StageRun, run_id)
                run.status = "succeeded"
                db.commit()
            self.check()
            return output
        except Exception:
            with Session() as db:
                run = db.get(StageRun, run_id)
                if run.status != "succeeded":
                    run.status = "failed" if received or not model else "uncertain"
                    db.commit()
            raise

    def current_guard(self, db):
        for entity_id, expected in self.payload.get("input_versions", {}).items():
            obj = db.get(Entity, entity_id)
            if not obj or obj.version != expected:
                raise ValueError("上游数据在任务运行期间发生变化，结果未覆盖当前工程，请基于新版本重试")

    def save_document(self, db, kind, scope, content):
        existing = store.one(db, self.project_id, kind, scope)
        return store.save(
            db,
            self.project_id,
            kind,
            scope,
            content,
            entity_id=existing.id if existing else None,
            expected=existing.version if existing else None,
            action="generated",
        )

    def save_assets(self, db, scope, assets, frames=None, preserve_ids=None):
        for asset in assets:
            local_id = asset["id"]
            entity_id = self.project_id + "_" + local_id
            existing = db.get(Entity, entity_id)
            content = clone(asset)
            content["image_ids"] = []
            if existing and local_id in (preserve_ids or set()):
                for key in ("image_ids", "image_views", "reference_image_ids", "reused_from"):
                    if key in existing.content:
                        content[key] = clone(existing.content[key])
            if frames:
                content["origin_kind"] = "video"
                evidence = next((e for e in asset["evidence"] if e["basis"] == "visual"), None)
                if evidence and evidence["shot_id"] in frames:
                    path = safe_path(frames[evidence["shot_id"]][0]["path"])
                    image = media.register(db, self.project_id, path, "reference")
                    content["image_ids"] = [image.id]
                    content["reference_image_ids"] = [image.id]
            store.save(
                db,
                self.project_id,
                "asset",
                scope,
                content,
                entity_id=entity_id,
                expected=existing.version if existing else None,
                action="generated",
            )

    def run(self):
        if self.kind in {"script_parse", "profiles"}:
            from .asset_workflows import enrich_profiles, parse_script

            return {"script_parse": parse_script, "profiles": enrich_profiles}[self.kind](self)
        handler = getattr(self, self.kind)
        return handler()

    def analysis(self):
        with Session() as db:
            record = db.get(Media, self.payload["media_id"])
            record_data = serialize(record)

        def prepare():
            with Session() as db:
                value = media.prepare(db, db.get(Media, record_data["id"]), self.check)
                db.commit()
                return value, None, None, None

        processed = self.step("媒体预处理", 8, record_data, prepare)
        if self.payload.get("subtitle_id"):
            with Session() as db:
                sub = db.get(Media, self.payload["subtitle_id"])
                transcript = {
                    "segments": media.parse_srt(
                        safe_path(sub.path).read_text(encoding="utf-8-sig"),
                        record_data["info"]["duration_ms"],
                    ),
                    "note": "使用用户字幕，尚未做独立音频比对",
                }
        elif processed["audio_path"] and settings.openai_transcribe_model:
            transcript = self.step(
                "语音转写",
                25,
                [record_data["sha256"], processed["audio_path"]],
                lambda: self.gateway.transcribe(processed["audio_path"]),
                model=settings.openai_transcribe_model,
            )
        else:
            transcript = {
                "segments": [],
                "mode": "visual_subtitles_only",
                "note": (
                    "当前服务未配置语音转写；仅提取关键帧中可读的字幕，可能遗漏对白。可上传 SRT 获得完整时间信息。"
                    if processed["audio_path"]
                    else "无音轨，跳过转写；仅提取关键帧可见字幕，可能遗漏。"
                ),
            }
        shots, assets = [], {}
        candidates = processed["shots"]
        for offset in range(0, len(candidates), 6):
            batch = candidates[offset : offset + 6]
            first, last = batch[0]["start_ms"], batch[-1]["end_ms"]
            segments = [s for s in transcript["segments"] if s["end_ms"] > first and s["start_ms"] < last]
            frames = [{**f, "shot_id": shot["id"]} for shot in batch for f in shot["frames"]]
            prompt = (
                "拆解原片候选镜头。每个输入镜头必须对应一个输出，严格保留 id 和时间范围，不自行添加镜头。"
                "资产ID使用 SRC_CHAR_001 / SRC_SCENE_001 / SRC_PROP_001 格式，并复用现有实体。"
                "证据中的 shot_id 必须来自本批次；visual 证据时间必须使用该镜头提供的实际帧 timestamp_ms。看不到的视角或无法确认的身份写未知。"
                "资产描述为可见特征；prompt 为日后整理参考的形象描述。"
                + (
                    "对白仅使用提供的字幕或转写片段，不假造说话人。\n"
                    if transcript["segments"]
                    else "没有语音转写。对白仅填写图像中确实可读的字幕；不凭表情猜测说话内容。uncertainty 标明仅关键帧字幕、可能遗漏对白和未知说话人。\n"
                )
                + prompt_json({"shots": batch, "transcript": segments, "known_assets": list(assets.values())})
            )
            output = self.model_step(
                f"镜头分析 {offset + 1}—{offset + len(batch)}",
                35 + round(35 * offset / len(candidates)),
                AnalysisBatch,
                prompt,
                images=frames,
                vision=True,
                model=settings.openai_vision_model,
                validate=lambda value, b=batch, known=assets: validate_batch(value, b, known),
            )
            expected = {s["id"]: s for s in batch}
            for shot in output["shots"]:
                ref = expected[shot["id"]]
                shot["frames"] = ref["frames"]
                shot["frame_media_ids"] = []
                shot["asset_ids"] = list(dict.fromkeys(shot["asset_ids"]))
            for asset in output["assets"]:
                asset["evidence"] = merge_evidence(
                    assets.get(asset["id"], {}).get("evidence", []), asset["evidence"]
                )
                assets[asset["id"]] = asset
            shots.extend(sorted(output["shots"], key=lambda shot: shot["start_ms"]))
        if any(not set(s["asset_ids"]).issubset(assets) for s in shots):
            raise ValueError("原片分镜存在无效资产引用")
        pattern = self.model_step(
            "剧情结构与创作规律",
            82,
            StoryPattern,
            "分析以下原片的冲突、节奏、反转与可复用创作规律，避免凭空补全剧情："
            + prompt_json({"shots": shots, "transcript": transcript}),
            model=settings.openai_text_model,
        )
        with Session() as db:
            self.current_guard(db)
            for shot in shots:
                for frame in shot["frames"]:
                    image = media.register(db, self.project_id, safe_path(frame["path"]), "reference")
                    shot["frame_media_ids"].append(image.id)
            content = {
                "media_id": record_data["id"],
                "media_sha256": record_data["sha256"],
                "preview_media_id": processed["preview_media_id"],
                "shots": shots,
                "transcript": transcript,
                "pattern": pattern,
                "note": "候选镜头和模型提取结果，需人工确认",
            }
            store.invalidate(db, self.project_id, ["analysis"], "source")
            for previous in db.scalars(
                select(Entity).where(
                    Entity.project_id == self.project_id, Entity.kind == "asset", Entity.scope == "source"
                )
            ).all():
                if previous.content.get("origin_kind", "video") == "video":
                    store.save(
                        db,
                        self.project_id,
                        "asset",
                        "source",
                        previous.content,
                        entity_id=previous.id,
                        expected=previous.version,
                        status="needs_update",
                        action="video_reanalysis",
                    )
            store.invalidate(db, self.project_id, ["brief", "outline", "production", "asset"], "adaptation")
            obj = self.save_document(db, "analysis", "source", content)
            self.save_assets(db, "source", list(assets.values()), {s["id"]: s["frames"] for s in candidates})
            db.commit()
            return {"entity_id": obj.id}

    def outline(self):
        brief = self.payload["brief"]
        source = self.payload["source"]
        prompt = (
            "根据已审核原片的创作规律和新的要求设计独立新故事。保留可复用节奏，重新设计人物目标、关系、事件因果、对白和结局。"
            "明确列出与原片的变化。输出可审核的大纲，人物和场景数量不得超过限制。"
            "若 brief.asset_strategy 为 reuse，沿用 brief._reused_assets 中的角色姓名、身份和外貌，重新设计事件与对白。"
            + prompt_json({"source": source, "brief": brief})
        )

        def validate_outline(value):
            if len(value["characters"]) > brief["max_characters"]:
                raise ValueError("大纲角色数量超过限制")

        output = self.model_step(
            "生成新故事大纲", 40, Outline, prompt, model=settings.openai_text_model, validate=validate_outline
        )
        with Session() as db:
            self.current_guard(db)
            store.invalidate(db, self.project_id, ["production", "asset"], "adaptation")
            obj = self.save_document(db, "outline", "adaptation", output)
            db.commit()
            return {"entity_id": obj.id}

    def production(self):
        from .asset_models import RichProduction
        from .services.asset_library import validate_profile

        reused = {x["content"]["id"]: x["content"] for x in self.payload.get("reused_assets", [])}
        prompt = (
            "根据已确认大纲生成中文剧本、可制作分镜和完整资产规划。剧本为 Markdown。资产必须使用 NEW_CHAR_/NEW_SCENE_/NEW_PROP_ 前缀，"
            "分镜仅引用本次资产 ID。资产 evidence 留空表示新创作。角色 prompt 包含肖像及正侧背全身形象卡要求；场景与道具提供独立提示词。"
            "镜头时长必须为正，总和在目标±10%内，角色与场景数量满足限制。对白不能超过可表演时长。"
            "每个角色提供完整 profile 人物档案：身份、性格、动机、背景、关系、面容、发型、体态、服装、声音、表演、一致性要求。未知字段和创作补全分别标注。"
            "如提供沿用资产，必须在资产规划中保留其 id、名称和外貌服装，不要另造一个同名新人物。输出质量注意事项，不宣称审核通过。"
            + prompt_json(
                {
                    "outline": self.payload["outline"],
                    "brief": self.payload["brief"],
                    "reused_assets": list(reused.values()),
                }
            )
        )

        def validate_output(value):
            validate_production(value, self.payload["brief"])
            if not set(reused).issubset({a["id"] for a in value["assets"]}):
                raise ValueError("制作方案遗漏了用户选择沿用的资产 ID")
            if any(a["type"] == "character" and not a.get("profile") for a in value["assets"]):
                raise ValueError("每个角色必须有完整 profile，未知信息要标注")
            for asset in value["assets"]:
                if asset["type"] == "character":
                    validate_profile(asset["profile"])

        output = self.model_step(
            "生成剧本、分镜与资产规划",
            35,
            RichProduction,
            prompt,
            model=settings.openai_text_model,
            validate=validate_output,
        )
        for asset in output["assets"]:
            if asset["id"] in reused:
                profile = {
                    **(asset.get("profile") or {}),
                    **{k: v for k, v in (reused[asset["id"]].get("profile") or {}).items() if v},
                }
                asset.update(clone(reused[asset["id"]]))
                if asset["type"] == "character":
                    asset["profile"] = profile
        with Session() as db:
            self.current_guard(db)
            store.invalidate(db, self.project_id, ["asset"], "adaptation")
            obj = self.save_document(db, "production", "adaptation", output)
            self.save_assets(db, "adaptation", output["assets"], preserve_ids=set(reused))
            db.commit()
            return {"entity_id": obj.id}

    def image(self):
        from .asset_workflows import generate_images

        return generate_images(self)

    def export(self):
        payload = self.payload
        return self.step(
            "冻结版本并打包",
            50,
            payload,
            lambda: (
                build_export(
                    payload["project"],
                    payload["entities"],
                    payload["media"],
                    self.job_id,
                    payload["include_reference"],
                    payload.get("revisions", []),
                ),
                None,
                None,
                None,
            ),
        )

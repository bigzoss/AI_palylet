import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Evidence(BaseModel):
    shot_id: str
    timestamp_ms: int = Field(ge=0)
    basis: Literal["visual", "dialogue", "inferred"]
    note: str


class AssetSpec(BaseModel):
    id: str
    type: Literal["character", "scene", "prop"]
    name: str
    description: str
    prompt: str
    evidence: list[Evidence]

    @model_validator(mode="after")
    def check_id(self):
        prefix = {"character": "CHAR", "scene": "SCENE", "prop": "PROP"}[self.type]
        if not re.fullmatch(rf"(?:SRC|NEW)_{prefix}_[A-Za-z0-9]+", self.id):
            raise ValueError("资产编号与类别不匹配，或包含非法字符")
        return self


class SourceShot(BaseModel):
    id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    shot_size: str
    camera: str
    action: str
    dialogue: str
    asset_ids: list[str]
    uncertainty: str

    @model_validator(mode="after")
    def check_range(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("镜头结束时间必须大于开始时间")
        return self


class AnalysisBatch(BaseModel):
    shots: list[SourceShot]
    assets: list[AssetSpec]


class StoryPattern(BaseModel):
    synopsis: str
    hook: str
    conflict: str
    escalation: list[str]
    reversal: str
    ending: str
    reusable_patterns: list[str]


class Brief(BaseModel):
    genre: str = Field(default="都市职场", max_length=200)
    audience: str = Field(default="面向成年观众，写实、紧凑、有反转", max_length=500)
    retain: str = Field(default="开场钩子、情绪起伏、反转节奏", max_length=1000)
    rewrite: str = Field(default="重构人物关系、核心事件、对白和结局", max_length=1000)
    requirements: str = Field(default="", max_length=4000)
    duration_seconds: int = Field(default=90, ge=30, le=180)
    max_characters: int = Field(default=3, ge=1, le=6)
    max_scenes: int = Field(default=2, ge=1, le=5)
    asset_strategy: Literal["redesign", "reuse"] = "redesign"
    reuse_asset_ids: list[str] = Field(default_factory=list, max_length=20)
    visual_style: str = Field(default="当代中国都市，自然光，写实摄影，9:16", max_length=1000)


class Outline(BaseModel):
    title: str
    logline: str
    characters: list[str]
    beats: list[str]
    ending: str
    changes_from_source: list[str]


class NewShot(BaseModel):
    id: str
    planned_duration_ms: int = Field(gt=0)
    shot_size: str
    camera: str
    action: str
    dialogue: str
    sound: str
    asset_ids: list[str]


class Production(BaseModel):
    title: str
    script: str
    shots: list[NewShot]
    assets: list[AssetSpec]
    quality_notes: list[str]


class EntityUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    content: dict


class ReviewRequest(BaseModel):
    entity_id: str
    expected_version: int = Field(ge=1)
    status: Literal["approved", "pending", "rejected"]


class JobRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=100)
    media_id: str | None = None
    subtitle_id: str | None = None
    entity_id: str | None = None
    expected_version: int | None = None
    include_reference: bool = False
    image_view: Literal["sheet", "portrait", "front", "side", "back"] = "sheet"


class AdaptationCreate(BaseModel):
    source_entity_id: str | None = None
    brief: Brief
    expected_source_version: int


class MergeRequest(BaseModel):
    source_id: str
    target_id: str
    source_version: int
    target_version: int


class SplitRequest(BaseModel):
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    shot_ids: list[str] = Field(min_length=1)


def validate_production(content: dict, brief: dict):
    result = Production.model_validate(content)
    ids = [a.id for a in result.assets]
    if len(ids) != len(set(ids)):
        raise ValueError("资产 ID 重复")
    if any(not x.startswith("NEW_") for x in ids):
        raise ValueError("新剧资产 ID 必须以 NEW_ 开头")
    if len({s.id for s in result.shots}) != len(result.shots) or not result.shots:
        raise ValueError("分镜为空或 ID 重复")
    for shot in result.shots:
        if not set(shot.asset_ids).issubset(ids):
            raise ValueError("分镜引用了不存在的资产")
    for kind, limit in [("character", brief["max_characters"]), ("scene", brief["max_scenes"])]:
        if sum(a.type == kind for a in result.assets) > limit:
            raise ValueError("角色或场景数量超过制作限制")
    target = brief["duration_seconds"] * 1000
    if not 0.9 * target <= sum(s.planned_duration_ms for s in result.shots) <= 1.1 * target:
        raise ValueError("分镜总时长不在目标 ±10% 内")
    return result

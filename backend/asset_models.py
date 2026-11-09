from typing import Literal

from pydantic import BaseModel, Field

from .schemas import AssetSpec, JobRequest, Production

ImageView = Literal["sheet", "portrait", "front", "side", "back"]
ProfileField = Literal[
    "role_type",
    "identity",
    "age",
    "gender",
    "personality",
    "motivation",
    "backstory",
    "relationships",
    "appearance",
    "hairstyle",
    "body",
    "clothing",
    "voice",
    "performance",
    "consistency",
]
VIEWS = {
    "sheet": "四视图形象卡",
    "portrait": "人物肖像",
    "front": "正面全身",
    "side": "侧面全身",
    "back": "背面全身",
}


class CharacterProfile(BaseModel):
    role_type: str = ""
    identity: str = ""
    age: str = ""
    gender: str = ""
    personality: str = ""
    motivation: str = ""
    backstory: str = ""
    relationships: str = ""
    appearance: str = ""
    hairstyle: str = ""
    body: str = ""
    clothing: str = ""
    voice: str = ""
    performance: str = ""
    consistency: str = ""
    inferred_fields: list[ProfileField] = Field(default_factory=list)
    unknown_fields: list[ProfileField] = Field(default_factory=list)


class ScriptAsset(AssetSpec):
    profile: CharacterProfile | None = None
    episode_name: str = ""


class ScriptScene(BaseModel):
    id: str
    title: str
    location_asset_id: str
    character_ids: list[str]
    prop_ids: list[str]
    action: str
    dialogue: str
    source_quote: str


class ScriptBreakdown(BaseModel):
    title: str
    synopsis: str
    assets: list[ScriptAsset]
    scenes: list[ScriptScene]
    creative_patterns: list[str]
    uncertainties: list[str]


class RichProduction(Production):
    assets: list[ScriptAsset]


class ScriptInput(BaseModel):
    expected_version: int | None = None
    title: str = Field(default="导入剧本", min_length=1, max_length=100)
    text: str = Field(min_length=20, max_length=20000)


class AssetCreate(BaseModel):
    scope: Literal["source", "adaptation"] = "source"
    type: Literal["character", "scene", "prop"]
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=4000)
    episode_name: str = Field(default="", max_length=100)
    prompt: str = Field(default="", max_length=8000)
    profile: CharacterProfile | None = None


class AssetTaskRequest(JobRequest):
    asset_ids: list[str] = Field(min_length=1, max_length=20)
    expected_versions: dict[str, int]
    image_view: ImageView = "sheet"


class ScriptParseRequest(JobRequest):
    expected_version: int

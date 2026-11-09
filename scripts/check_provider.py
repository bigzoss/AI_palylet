"""Explicit real-provider smoke check. Prints metadata only, never credentials."""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from pydantic import BaseModel

from backend.config import safe_path, settings
from backend.db import now
from backend.services.gateway import Gateway


class Probe(BaseModel):
    answer: str


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--images", action="store_true", help="Also generate one image and edit it once (may incur charges)"
    )
    args = parser.parse_args()
    report = {
        "checked_at": now(),
        "provider": settings.provider_name,
        "base_url": settings.openai_base_url,
        "protocol": settings.api_mode,
        "checks": [],
    }
    gateway = Gateway()
    directory = safe_path("diagnostics")
    directory.mkdir(parents=True, exist_ok=True)

    def check(name, fn):
        start = time.monotonic()
        try:
            metadata = fn()
            row = {
                "check": name,
                "status": "passed",
                "elapsed_ms": round((time.monotonic() - start) * 1000),
                **metadata,
            }
        except Exception as exc:
            row = {"check": name, "status": "failed", "error_class": type(exc).__name__}
            if getattr(exc, "status_code", None):
                row["http_status"] = exc.status_code
        report["checks"].append(row)
        print(json.dumps(row, ensure_ascii=False))

    check("model_list", lambda: {"models": [x["id"] for x in gateway.list_models()]})

    def structured(vision=False):
        images = None
        prompt = "请返回 answer 为 ready 的 JSON 对象。"
        if vision:
            path = directory / "red-square.jpg"
            Image.new("RGB", (64, 64), "red").save(path)
            images = [
                {"path": path.relative_to(settings.storage).as_posix(), "shot_id": "PROBE", "timestamp_ms": 0}
            ]
            prompt = "识别图片的纯色颜色，answer 用中文写颜色名称。"
        value, usage, request_id, model = gateway.structured(Probe, prompt, images=images, vision=vision)
        if not value.get("answer") or (vision and "红" not in value["answer"]):
            raise ValueError("Unexpected probe result")
        return {"model": model, "usage": usage, "request_id": request_id}

    check("text_structured", lambda: structured(False))
    check("vision_structured", lambda: structured(True))
    if args.images:

        def image(reference=None):
            result, usage, request_id, model = gateway.image(
                "A plain blue ceramic mug on white background, clean product photograph, no text."
                if not reference
                else "Preserve this mug shape and composition, change its color to green, white background, no text.",
                reference,
            )
            path = directory / ("image-edit.png" if reference else "image-generation.png")
            path.write_bytes(base64.b64decode(result["base64"]))
            with Image.open(path) as picture:
                picture.verify()
            return {
                "model": model,
                "request_id": request_id,
                "usage": usage.model_dump() if hasattr(usage, "model_dump") else usage,
                "file": path.relative_to(settings.storage).as_posix(),
            }

        check("image_generation", image)
        reference = directory / "image-generation.png"
        if reference.exists():
            check("image_edit", lambda: image(reference.relative_to(settings.storage).as_posix()))
    report["transcription"] = {
        "model": settings.openai_transcribe_model or None,
        "status": "not_tested" if settings.openai_transcribe_model else "not_configured",
        "fallback": "SRT or visible subtitles in sampled frames",
    }
    target = directory / "provider-check.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Report: data/diagnostics/provider-check.json")
    return 1 if any(x["status"] == "failed" for x in report["checks"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())

import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import settings
from backend.database import public_database_info
from backend.db import engine
from backend.services.media import ffmpeg


def main():
    report = {
        "python": sys.version.split()[0],
        "node_available": bool(shutil.which("node")),
        "storage": str(settings.storage),
        "api_key_configured": bool(settings.openai_api_key),
        "provider": settings.provider_name,
        "base_url": settings.openai_base_url,
        "protocol": settings.api_mode,
        "image_size": settings.image_size,
        "database": public_database_info(engine),
        "models_configured": {
            k: bool(getattr(settings, f"openai_{k}_model")) for k in ["vision", "text", "transcribe", "image"]
        },
    }
    try:
        result = subprocess.run([ffmpeg(), "-version"], capture_output=True, check=True, timeout=20)
        report["ffmpeg"] = result.stdout.decode(errors="replace").splitlines()[0]
    except Exception:
        report["ffmpeg"] = "unavailable"
    report["packages"] = {
        name: importlib.metadata.version(name) for name in ["fastapi", "sqlalchemy", "openai", "scenedetect"]
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

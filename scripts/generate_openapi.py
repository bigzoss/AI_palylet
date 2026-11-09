import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from backend.main import app  # noqa: E402

(root / "openapi.json").write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
print("Wrote openapi.json (public API schema only)")

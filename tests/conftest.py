import os
import tempfile

# Never connect tests to the user's live workspace or provider.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="framecraft-tests-")
os.environ["DATABASE_URL"] = ""
os.environ["MYSQL_HOST"] = ""
os.environ["MYSQL_LOCAL_MANAGED"] = "false"
os.environ["OPENAI_API_KEY"] = ""
os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
os.environ["OPENAI_API_MODE"] = "auto"
os.environ["TEACHER_MODEL"] = ""
os.environ["OPENAI_TEXT_MODEL"] = ""
os.environ["OPENAI_VISION_MODEL"] = ""
os.environ["OPENAI_IMAGE_MODEL"] = ""
os.environ["OPENAI_TRANSCRIBE_MODEL"] = "whisper-1"
os.environ["AUTH_USERNAME"] = "test-admin"
os.environ["AUTH_PASSWORD"] = "test-password-only"

import pytest
from fastapi.testclient import TestClient

from backend.db import Base, engine
from backend.main import app


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"username": "test-admin", "password": "test-password-only"})
        yield client

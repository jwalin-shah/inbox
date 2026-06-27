import pytest
from fastapi.testclient import TestClient
from inbox_server import app
import tempfile
import pathlib

def test_fastapi_boot_crash(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        monkeypatch.setattr("services.TOKENS_DIR", tdp)
        monkeypatch.setattr("services.TOKEN_FILE", tdp / "token.json")
        monkeypatch.setattr("services.CREDS_FILE", tdp / "credentials.json")
        monkeypatch.setenv("INBOX_PRE_WARM_CONVERSATIONS", "0")
        monkeypatch.setenv("INBOX_DISABLE_AMBIENT", "1")
        
        # This will trigger the lifespan events
        with TestClient(app) as client:
            pass

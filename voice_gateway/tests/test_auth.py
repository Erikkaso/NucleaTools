from io import BytesIO

import pytest

from test_gateway import gateway, setup_dependencies, ticket


KEY = "test-only-not-a-real-secret-" + "a" * 32


@pytest.mark.parametrize("key", ["", "short", "x" * 129, "x" * 31 + " "])
def test_missing_or_invalid_key_does_not_call_dependencies(gateway, monkeypatch, key):
    monkeypatch.setattr(gateway.requests, "post", lambda *a, **k: pytest.fail("No upstream call"))
    result = gateway.app.test_client().post("/api/device-audio", headers={"X-Nuclea-Key": key})
    assert result.status_code == 401
    assert result.json["code"] == "authentication_required"


def test_key_reaches_only_n8n_and_is_not_logged_or_returned(gateway, monkeypatch, caplog):
    upstream, calls = setup_dependencies(gateway, monkeypatch)
    result = gateway.app.test_client().post("/api/device-audio", headers={"X-Nuclea-Key": KEY},
        data={"audio": (BytesIO(b"RIFFtest"), "command.wav")})
    assert result.status_code == 200
    assert calls[0][2]["headers"]["X-Nuclea-Key"] == KEY
    assert "X-Nuclea-Key" not in calls[1][2]["headers"]
    assert KEY not in str(result.headers) + result.get_data(as_text=True) + caplog.text
    result.close()


@pytest.mark.parametrize("status", [401, 403])
def test_n8n_rejection_never_accesses_tts(gateway, monkeypatch, status):
    monkeypatch.setattr(gateway.requests, "post", lambda *a, **k: ticket(status=status))
    monkeypatch.setattr(gateway.requests, "get", lambda *a, **k: pytest.fail("No TTS on rejected key"))
    result = gateway.app.test_client().post("/api/device-audio", headers={"X-Nuclea-Key": KEY},
        data={"audio": (BytesIO(b"RIFFtest"), "command.wav")})
    assert result.status_code == status
    assert result.json["code"] == "authentication_failed"

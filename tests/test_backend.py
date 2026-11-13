import pytest

from aaby.api import create_app
from aaby.knowledge import read_instruction, search_instructions


@pytest.fixture
def client(tmp_path):
    return create_app(str(tmp_path / "test.sqlite3")).test_client()


def payload(elements=None):
    return {"message": "Нужен доступ", "page": {
        "snapshot_id": "snap-1", "url": "https://demo.invalid/access", "title": "Доступы",
        "elements": elements or [],
    }}


def test_guidance_and_persistence(client):
    sid = client.post("/v1/sessions").json["id"]
    turn = payload([{"id": "e1", "role": "button", "label": "Запросить доступ"}])
    response = client.post(f"/v1/sessions/{sid}/turns", json=turn)
    assert response.status_code == 200
    assert response.json["highlight_element_id"] == "e1"
    assert response.json["snapshot_id"] == "snap-1"
    session = client.get(f"/v1/sessions/{sid}").json
    assert session["status"] == "waiting_user"
    assert session["hints"] == [response.json]
    assert "message" not in session


@pytest.mark.parametrize("elements", [
    [],
    [{"id": "e1", "role": "button", "label": "Запросить доступ", "disabled": True}],
    [{"id": "e1", "role": "textbox", "label": "Запросить доступ"}],
    [{"id": "e1", "role": "button", "label": "Запросить доступ"},
     {"id": "e2", "role": "button", "label": "Запросить доступ"}],
])
def test_ambiguous_or_missing_target_never_guessed(client, elements):
    sid = client.post("/v1/sessions").json["id"]
    result = client.post(f"/v1/sessions/{sid}/turns", json=payload(elements)).json
    assert result["status"] == "needs_context"
    assert result["highlight_element_id"] is None


def test_not_found_and_health(client):
    assert client.get("/health").json == {"status": "ok", "mode": "demo"}
    assert client.get("/v1/sessions/missing").status_code == 404
    assert client.post("/v1/sessions/missing/turns", json=payload()).status_code == 404


def test_validation(client):
    sid = client.post("/v1/sessions").json["id"]
    url = f"/v1/sessions/{sid}/turns"
    assert client.post(url, json={}).status_code == 422
    assert client.post(url, data="{", content_type="application/json").status_code == 400
    assert client.post(url, data=" " * 8_000_001, content_type="application/json").status_code == 413
    duplicate = {"id": "same", "role": "button", "label": "x"}
    assert client.post(url, json=payload([duplicate, duplicate])).status_code == 422


def test_data_survives_restart(tmp_path):
    path = str(tmp_path / "persistent.sqlite3")
    first = create_app(path).test_client()
    sid = first.post("/v1/sessions").json["id"]
    first.post(f"/v1/sessions/{sid}/turns", json=payload())
    second = create_app(path).test_client()
    assert len(second.get(f"/v1/sessions/{sid}").json["hints"]) == 1


def test_unsupported_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("AABY_AGENT_MODE", "live")
    with pytest.raises(ValueError, match="Unsupported"):
        create_app(str(tmp_path / "test.sqlite3"))


def test_knowledge():
    assert search_instructions("permission denied")[0]["synthetic"] is True
    assert search_instructions("погода") == []
    assert read_instruction("demo-access-v1")["id"] == "demo-access-v1"
    with pytest.raises(ValueError):
        read_instruction("missing")

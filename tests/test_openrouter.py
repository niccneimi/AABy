import asyncio
import base64
import io
import json

import httpx
import pytest
from PIL import Image

from aaby.contracts import Turn, Screenshot
from aaby.errors import AgentError
from aaby.openrouter import OpenRouterAgent, OpenRouterConfig
from aaby.privacy import image_url, redact


def turn(screenshot=None):
    return Turn.model_validate({"message": "Нужен доступ token=very-secret", "page": {
        "snapshot_id": "snap-2", "url": "https://demo.invalid", "title": "Доступы",
        "screenshot": screenshot,
        "elements": [{"id": "e1", "role": "button", "label": "Запросить доступ"},
                     {"id": "disabled", "role": "button", "label": "X", "disabled": True}],
    }})


def picture():
    output = io.BytesIO()
    Image.new("RGB", (2, 2)).save(output, "PNG")
    return {"mime_type": "image/png", "base64": base64.b64encode(output.getvalue()).decode()}


class Knowledge:
    async def search(self, query):
        assert "very-secret" not in query
        return [{"id": "doc1", "text": "Synthetic instruction"}]


def answer(**updates):
    result = {"text": "Нажми кнопку", "status": "waiting_user",
              "highlight_element_id": "e1", "source_ids": ["doc1"]}
    result.update(updates)
    return result


def run_model(result=None, handler=None, screenshot=None):
    async def run():
        def default(request):
            body = json.loads(request.content)
            assert body["response_format"]["json_schema"]["strict"] is True
            assert "very-secret" not in str(body)
            assert "private-key" not in str(body)
            assert body["model"] == "test/model"
            assert request.headers["Authorization"] == "Bearer private-key"
            if screenshot:
                assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;")
            return httpx.Response(200, json={"choices": [{
                "finish_reason": "stop", "message": {"content": json.dumps(result or answer())},
            }]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler or default)) as client:
            agent = OpenRouterAgent(OpenRouterConfig("private-key", "test/model"), client, Knowledge())
            return await agent.respond(turn(screenshot), [])
    return asyncio.run(run())


def test_multimodal_guidance():
    hint = run_model(screenshot=picture())
    assert hint.snapshot_id == "snap-2"
    assert hint.highlight_element_id == "e1"
    assert hint.mode == "openrouter"
    assert run_model(answer(highlight_element_id=None)).highlight_element_id is None


@pytest.mark.parametrize("updates,code", [
    ({"highlight_element_id": "invented"}, "model_invalid_target"),
    ({"highlight_element_id": "disabled"}, "model_invalid_target"),
    ({"status": "needs_context"}, "model_invalid_target"),
    ({"source_ids": ["invented"]}, "model_invalid_sources"),
    ({"status": "completed"}, "model_invalid_response"),
    ({"text": ""}, "model_invalid_response"),
])
def test_invalid_model_decision(updates, code):
    with pytest.raises(AgentError, match=code):
        run_model(answer(**updates))


@pytest.mark.parametrize("status,body,code", [
    (401, {"error": "private provider message"}, "model_unavailable"),
    (429, {}, "model_unavailable"),
    (200, {"error": "private provider message"}, "model_unavailable"),
    (200, {"choices": []}, "model_invalid_response"),
    (200, {"choices": [{"finish_reason": "length"}]}, "model_incomplete_response"),
    (200, {"choices": [{"finish_reason": "stop", "message": {"content": "invalid"}}]}, "model_invalid_response"),
])
def test_provider_failures(status, body, code):
    with pytest.raises(AgentError, match=code):
        run_model(handler=lambda request: httpx.Response(status, json=body))


def test_timeout():
    def timeout(request):
        raise httpx.ReadTimeout("private provider message")
    with pytest.raises(AgentError, match="model_timeout"):
        run_model(handler=timeout)


def test_configuration(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    with pytest.raises(ValueError, match="Set OPENROUTER"):
        OpenRouterConfig.from_env()
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
    config = OpenRouterConfig.from_env()
    assert config.model == "test/model"
    assert "private-key" not in repr(config)


def test_redaction():
    assert "topsecret" not in redact("Bearer topsecret token=topsecret password=topsecret")
    assert redact("sk-123456789") == "[REDACTED]"
    assert redact("eyJabc.abc.def") == "[REDACTED]"


@pytest.mark.parametrize("mime,data", [
    ("image/png", "not base64!"),
    ("image/png", base64.b64encode(b"not an image").decode()),
    ("image/jpeg", picture()["base64"]),
])
def test_invalid_image(mime, data):
    with pytest.raises(AgentError, match="invalid_image"):
        image_url(Screenshot(mime_type=mime, base64=data))

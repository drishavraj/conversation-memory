import copy
import json

import httpx
import pytest
from pydantic import ValidationError

from app.pipeline import KnowledgeExtraction
from app.provider import GeminiProvider, gemini_response_schema
from app.task_providers import strict_schema


def test_gemini_schema_preserves_local_and_openai_constraints():
    original = KnowledgeExtraction.model_json_schema()
    before = copy.deepcopy(original)
    sent = gemini_response_schema(original)
    assert "maxItems" not in sent["properties"]["items"]
    assert original == before
    assert original["properties"]["items"]["maxItems"] == 500
    assert strict_schema(original)["properties"]["items"]["maxItems"] == 500
    assert sent["$defs"] == original["$defs"]
    assert sent["required"] == original["required"]


@pytest.mark.parametrize("count", [1, 501])
def test_gemini_request_omits_bound_but_response_is_still_validated(count):
    item = {
        "kind": "action", "text": "Send checklist",
        "evidence": "I will send the checklist.", "certainty": "explicit",
    }
    result = {"suggested_theme": "office", "items": [item] * count}

    def handler(request):
        body = json.loads(request.content)
        schema = body["generationConfig"]["responseJsonSchema"]
        # Reproduce the live provider's rejection of the original request.
        if "maxItems" in schema["properties"]["items"]:
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": json.dumps(result)}]},
        }]})

    provider = GeminiProvider("test-key", "test-model", httpx.MockTransport(handler))
    if count > 500:
        with pytest.raises(ValidationError):
            provider.generate(KnowledgeExtraction, "Extract", {"source": item["evidence"]})
    else:
        parsed = provider.generate(KnowledgeExtraction, "Extract", {"source": item["evidence"]})
        assert len(parsed.items) == 1

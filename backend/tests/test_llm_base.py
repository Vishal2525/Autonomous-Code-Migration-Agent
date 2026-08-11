from pydantic import BaseModel, Field

from app.llm.base import sanitize_schema


class Inner(BaseModel):
    name: str
    count: int = 1


class Outer(BaseModel):
    title: str = Field(description="a title")
    maybe: str | None = None
    items: list[Inner] = []


def test_refs_are_inlined():
    schema = sanitize_schema(Outer.model_json_schema())
    assert "$defs" not in schema
    items_schema = schema["properties"]["items"]["items"]
    assert "$ref" not in str(schema)
    assert items_schema["properties"]["name"]["type"] == "string"


def test_gemini_nullable_collapse():
    schema = sanitize_schema(Outer.model_json_schema(), for_gemini=True)
    maybe = schema["properties"]["maybe"]
    assert maybe.get("type") == "string"
    assert maybe.get("nullable") is True
    assert "anyOf" not in maybe


def test_noise_keys_removed():
    schema = sanitize_schema(Outer.model_json_schema())
    assert "title" not in schema
    assert "default" not in schema["properties"].get("items", {})

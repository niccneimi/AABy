from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Element(Contract):
    id: str = Field(min_length=1, max_length=100)
    role: Literal["button", "link", "textbox", "combobox", "other"]
    label: str = Field(max_length=500)
    disabled: bool = False


class Screenshot(Contract):
    mime_type: Literal["image/png", "image/jpeg"]
    base64: str = Field(min_length=1, max_length=6_000_000)


class Page(Contract):
    snapshot_id: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(max_length=500)
    screenshot: Screenshot | None = None
    elements: list[Element] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def unique_elements(self):
        if len({element.id for element in self.elements}) != len(self.elements):
            raise ValueError("Element IDs must be unique within a snapshot")
        return self


class Turn(Contract):
    message: str = Field(min_length=1, max_length=4000)
    page: Page


class Hint(Contract):
    snapshot_id: str
    text: str
    status: Literal["needs_context", "waiting_user", "waiting_service", "completed"]
    highlight_element_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    mode: Literal["demo", "openrouter"] = "demo"


class RunRequest(Turn):
    request_id: str = Field(min_length=1, max_length=100)


class ModelHint(Contract):
    # No completed state: only the service may establish completion in a future integration.
    text: str = Field(min_length=1, max_length=4000)
    status: Literal["needs_context", "waiting_user", "waiting_service"]
    highlight_element_id: str | None
    source_ids: list[str] = Field(max_length=10)

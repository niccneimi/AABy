from typing import Protocol

from aaby.contracts import Hint, Turn
from aaby.knowledge import INSTRUCTION


class Agent(Protocol):
    def respond(self, turn: Turn) -> Hint: ...


class DemoAgent:
    """Deterministic contract demonstration; does not interpret screenshots."""

    def respond(self, turn: Turn) -> Hint:
        base = {"snapshot_id": turn.page.snapshot_id, "source_ids": [INSTRUCTION["id"]]}
        candidates = [
            e for e in turn.page.elements
            if e.label.casefold() == "запросить доступ" and not e.disabled
            and e.role in ("button", "link")
        ]
        if len(candidates) == 1:
            return Hint(
                **base, text="Нажми «Запросить доступ», чтобы открыть форму.",
                status="waiting_user", highlight_element_id=candidates[0].id,
            )
        return Hint(
            **base, status="needs_context",
            text=("Демонстрационный режим: не удалось однозначно найти кнопку "
                  "«Запросить доступ». Открой нужную страницу или уточни, где застрял. "
                  "Анализ скриншота моделью пока не подключён."),
        )


"""Synthetic demo instructions, never presented as Avito policy."""

INSTRUCTION = {
    "id": "demo-access-v1",
    "title": "Тестовый сценарий запроса доступа",
    "synthetic": True,
    "text": (
        "Откройте форму «Запросить доступ». Выберите ресурс и роль согласно "
        "инструкции своей команды. Укажите обоснование и проверьте данные. "
        "Отправьте запрос самостоятельно. Создание запроса не означает выдачу доступа. "
        "Если роль неизвестна, уточните её у наставника."
    ),
}


def search_instructions(query: str) -> list[dict]:
    if any(word in query.lower() for word in ("доступ", "permission", "access")):
        return [dict(INSTRUCTION)]
    return []


def read_instruction(instruction_id: str) -> dict:
    if instruction_id != INSTRUCTION["id"]:
        raise ValueError("Unknown instruction")
    return dict(INSTRUCTION)

from backend.scoring.prompt import build_system, build_user


def _checklist():
    return {
        "name": "QA",
        "notes": [],
        "criteria": [{
            "id": "contact",
            "title": "Приветствие",
            "answer_type": "binary",
            "weight": 10,
            "description": "Оператор поздоровался.",
            "na_allowed": False,
            "lower_if": ["Не поздоровался"],
            "keep_if": ["Клиент первым начал разговор и оператор сразу ответил по делу"],
        }],
    }


def test_system_prompt_keeps_decision_rules_but_requests_compact_explanations():
    prompt = build_system(_checklist(), only=["contact"])

    assert "keep_if имеет приоритет" in prompt
    assert "Оценивай только фактические действия и реплики оператора" in prompt
    assert "максимум ОДНО короткое предложение" in prompt
    assert "до 18 слов на язык" in prompt
    assert "Верни только объект по JSON Schema" in prompt
    assert "contact — Приветствие" in prompt
    assert len(prompt) < 5000


def test_user_prompt_keeps_full_indexed_transcript():
    dialog = {
        "conversation_id": "test-ru-001",
        "channel": "agent chat",
        "language": "RU",
        "transcript": [
            {"timestamp": "00:01", "speaker": "client", "text": "Здравствуйте"},
            {"timestamp": "00:02", "speaker": "operator", "text": "Добрый день"},
        ],
    }

    prompt = build_user(dialog, only=["contact"])

    assert "[0] 00:01 client: Здравствуйте" in prompt
    assert "[1] 00:02 operator: Добрый день" in prompt
    assert "Оцени только: contact" in prompt

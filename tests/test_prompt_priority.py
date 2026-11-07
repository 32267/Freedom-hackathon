from backend.scoring.prompt import build_system


def test_prompt_prioritizes_applicability_and_keep_if_over_lower_if():
    checklist = {
        "name": "Test checklist",
        "notes": [],
        "criteria": [
            {
                "id": "identification",
                "title": "Identification",
                "answer_type": "binary",
                "weight": 10,
                "description": "Yes if identity is confirmed.",
                "na_allowed": True,
                "na_rule": "No protected data was disclosed and no protected action was taken.",
                "lower_if": ["Verification was not confirmed."],
                "keep_if": ["Operator correctly stopped; choose N/A, not No."],
            }
        ],
    }

    prompt = build_system(checklist)

    applicability = prompt.index("Сначала проверь применимость критерия")
    keep_if_priority = prompt.index("Они имеют приоритет над общими условиями lower_if")
    criterion_rules = prompt.index("Снижай (Нет / ниже ступень), если:")
    assert applicability < keep_if_priority < criterion_rules
    assert "Не превращай такую ситуацию в no." in prompt
    assert "Не используй lower_if, чтобы отменить применимое исключение keep_if." in prompt


def test_prompt_tells_model_to_evaluate_only_operator_actions():
    prompt = build_system({"name": "Test", "notes": [], "criteria": []})

    assert "Оцени только фактические действия и реплики оператора." in prompt
    assert "Не приписывай оператору действия клиента, бота или system" in prompt
    assert "Если фактов недостаточно, не выдумывай их" in prompt



def test_prompt_contains_observed_semantic_regression_guardrails():
    from pathlib import Path
    import json

    root = Path(__file__).parent.parent
    checklist = json.loads((root / "checklists/default.json").read_text())
    prompt = build_system(checklist)

    assert "Не считай раскрытием конфиденциальной информации имя самого оператора" in prompt
    assert "только при раскрытии данных третьих лиц или внутренних данных компании" in prompt
    assert "Не оценивай ожидание в очереди и задержку до подключения" in prompt
    assert "после того, как оператор вступил в диалог" in prompt
    assert "одно и то же решение и факты" in prompt

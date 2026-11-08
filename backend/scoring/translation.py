"""Translate finalized criterion explanations without changing scoring decisions."""
from backend.llm import LLMOutputError, call_json

LANGS = ("ru", "kz", "en")
def translate_explanations(evaluation: dict, dialog: dict, checklist: dict, spec: str | None = None) -> dict:
    """Translate source-language explanations once after ensemble voting; scoring fields are immutable."""
    source_lang = {"RU": "ru", "KZ": "kz", "EN": "en"}.get(str(dialog.get("language", "RU")).upper(), "ru")
    results = evaluation["results"]
    properties = {}
    payload = {}
    for result in results:
        cid = result["criterion_id"]
        properties[cid] = {
            "type": "object",
            "properties": {
                "explanations": {"type": "object", "properties": {
                    lang: {"type": "string"} for lang in LANGS},
                    "required": list(LANGS), "additionalProperties": False},
                "na_reasons": {"type": "object", "properties": {
                    lang: {"type": "string"} for lang in LANGS},
                    "required": list(LANGS), "additionalProperties": False},
            },
            "required": ["explanations", "na_reasons"],
            "additionalProperties": False,
        }
        payload[cid] = {
            "answer": result["answer"],
            "explanation": result.get("_source_explanation", ""),
            "na_reason": result.get("_source_na_reason", "") if result["answer"] == "na" else "",
        }

    schema = {
        "type": "object",
        "properties": {"criteria": {"type": "object", "properties": properties,
                                    "required": list(properties), "additionalProperties": False}},
        "required": ["criteria"], "additionalProperties": False,
    }
    system = (
        "You are a professional translator for customer-support quality evaluations. "
        "Translate only the supplied explanation and N/A reason into Russian (ru), Kazakh (kz), "
        "and English (en). Do not reassess the dialog or change scores, answers, evidence, flags, "
        "or meaning. Keep names, numbers, criterion terminology, and factual claims unchanged. "
        "The translation in the dialog's source language must be copied exactly, character for character. "
        "For non-N/A answers, every na_reason must be an empty string. For N/A answers, translate the reason. "
        "Return only the JSON object matching the schema."
    )
    user = (
        f"Dialog language: {dialog.get('language', 'RU')} (canonical explanation language: {source_lang}).\n"
        "Translate these finalized explanations. Do not add facts or qualifications.\n"
        + __import__("json").dumps({"criteria": payload}, ensure_ascii=False)
    )
    response = call_json(system, user, schema, spec)
    translated = response.data.get("criteria", {})
    for result in results:
        cid = result["criterion_id"]
        item = translated.get(cid)
        if not isinstance(item, dict):
            raise LLMOutputError(f"Translation missing criterion {cid}")
        explanations = item.get("explanations")
        na_reasons = item.get("na_reasons")
        if not isinstance(explanations, dict) or not isinstance(na_reasons, dict):
            raise LLMOutputError(f"Translation has invalid language maps for {cid}")
        source_text = result.get("_source_explanation", "")
        source_reason = result.get("_source_na_reason", "") if result["answer"] == "na" else ""
        for lang in LANGS:
            if not isinstance(explanations.get(lang), str) or not explanations[lang].strip():
                raise LLMOutputError(f"Translation explanation missing {lang} for {cid}")
            if not isinstance(na_reasons.get(lang), str):
                raise LLMOutputError(f"Translation N/A reason invalid for {lang} in {cid}")
        if explanations[source_lang] != source_text:
            raise LLMOutputError(f"Translation changed canonical {source_lang} explanation for {cid}")
        if result["answer"] == "na":
            if any(not na_reasons[lang].strip() for lang in LANGS):
                raise LLMOutputError(f"Translation N/A reason missing for {cid}")
            if na_reasons[source_lang] != source_reason:
                raise LLMOutputError(f"Translation changed canonical {source_lang} N/A reason for {cid}")
        elif any(na_reasons[lang] for lang in LANGS):
            raise LLMOutputError(f"Translation added an N/A reason to non-N/A criterion {cid}")
        result["explanations"] = {lang: explanations[lang].strip() for lang in LANGS}
        result["explanation"] = result["explanations"]["ru"]
        result["na_reasons"] = ({lang: na_reasons[lang].strip() for lang in LANGS}
                                if result["answer"] == "na" else None)
        result["na_reason"] = result["na_reasons"]["ru"] if result["na_reasons"] else None
        result.pop("_source_language", None)
        result.pop("_source_explanation", None)
        result.pop("_source_na_reason", None)

    evaluation["cost_usd"] = round(evaluation.get("cost_usd", 0) + response.cost_usd, 6)
    tokens = evaluation.setdefault("tokens", {})
    for key, value in (("input", response.input_tokens), ("output", response.output_tokens),
                       ("cache_read", response.cache_read_tokens)):
        tokens[key] = tokens.get(key, 0) + value
    tokens["calls"] = tokens.get("calls", 0) + 1
    return evaluation

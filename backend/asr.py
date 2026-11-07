"""MP3/WAV → диалог в формате организаторов: распознавание речи (faster-whisper) + разметка ролей моделью.

Whisper не различает говорящих, поэтому после распознавания LLM (тот же оценщик из LLM_PROVIDERS) по смыслу
размечает каждую реплику: operator / client / bot / system. Если разметить не удалось — роль «client»
(оценка покажет, что реплик оператора нет, и ничего не будет выдумано).

Настройки (.env): ASR_MODEL=small (tiny|base|small|medium|large-v3), ASR_DEVICE=auto, ASR_COMPUTE=int8.
Модель скачивается с Hugging Face при первом распознавании и кэшируется.
"""
import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone

from backend.llm import LLMError, call_json, provider_tiers

LANG_MAP = {"ru": "RU", "kk": "KZ", "kz": "KZ", "en": "EN"}
_model = None
_model_lock = threading.Lock()


def _whisper():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(os.getenv("ASR_MODEL", "small"), device=os.getenv("ASR_DEVICE", "auto"),
                                  compute_type=os.getenv("ASR_COMPUTE", "int8"))
        return _model


def load_audio(path: str, sr: int = 16000):
    """Декодирование через ffmpeg → моно float32 16 кГц (не зависим от версии PyAV)."""
    import numpy as np
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("Нужен ffmpeg для распознавания аудио (brew install ffmpeg)")
    out = subprocess.run([exe, "-nostdin", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


def transcribe(path: str, language: str | None = None) -> tuple[list[dict], str]:
    """→ ([{start, end, text}], код языка whisper)."""
    lang = {"RU": "ru", "KZ": "kk", "EN": "en"}.get((language or "").upper())
    segments, info = _whisper().transcribe(load_audio(path), language=lang, vad_filter=True, beam_size=5)
    out = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments if s.text.strip()]
    return out, info.language


ROLE_SCHEMA = {
    "type": "object",
    "properties": {"roles": {"type": "array", "items": {
        "type": "object",
        "properties": {"i": {"type": "integer"}, "speaker": {"type": "string", "enum": ["operator", "client", "bot", "system"]}},
        "required": ["i", "speaker"], "additionalProperties": False}}},
    "required": ["roles"], "additionalProperties": False,
}

ROLE_SYSTEM = """Ты размечаешь роли в автоматической расшифровке телефонного звонка в поддержку брокера Freedom Broker.
Роли: operator — сотрудник поддержки; client — клиент; bot — голосовое меню/автоответчик (приветствие, «нажмите 1»,
согласие на обработку данных); system — служебные сообщения. Расшифровка может быть с ошибками.
Для каждой реплики по номеру верни роль. Опирайся на смысл: кто задаёт вопрос о своём счёте — клиент; кто
представляется от компании, проверяет данные, объясняет порядок — оператор."""


def label_roles(segments: list[dict]) -> list[str]:
    roles = ["client"] * len(segments)
    if not segments:
        return roles
    user = "\n".join(f"[{i}] {s['text']}" for i, s in enumerate(segments))
    spec = provider_tiers()[0][0]
    try:
        res = call_json(ROLE_SYSTEM, f"Расшифровка звонка:\n{user}", ROLE_SCHEMA, spec)
    except LLMError:
        return roles
    for r in res.data.get("roles", []):
        if isinstance(r.get("i"), int) and 0 <= r["i"] < len(roles):
            roles[r["i"]] = r["speaker"]
    return roles


def audio_to_dialog(path: str, conversation_id: str, language: str | None = None) -> dict:
    segments, detected = transcribe(path, language)
    roles = label_roles(segments)
    base = datetime.now(timezone.utc).replace(microsecond=0)
    transcript = [{"timestamp": (base + timedelta(seconds=s["start"])).isoformat(), "speaker": role, "text": s["text"]}
                  for s, role in zip(segments, roles)]
    transcript.insert(0, {"timestamp": base.isoformat(), "speaker": "system",
                          "text": "Запись загружена вручную и расшифрована автоматически (Whisper); роли размечены моделью."})
    return {
        "conversation_id": conversation_id,
        "channel": "voice call",
        "language": (language or "").upper() or LANG_MAP.get(detected, detected.upper()),
        "transcript": transcript,
        "audio_url": None,
        "dataset_group_id": "UPLOAD",
    }

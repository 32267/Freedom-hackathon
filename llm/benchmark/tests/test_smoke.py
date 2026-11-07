import unittest

from llm.benchmark.smoke import select_smoke_dialogs, validate_evaluation


class SmokeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.dialogs = [
            {"conversation_id": "ru-chat", "language": "RU", "channel": "agent chat"},
            {"conversation_id": "kz-chat", "language": "KZ", "channel": "agent chat"},
            {"conversation_id": "en-chat", "language": "EN", "channel": "agent chat"},
            {"conversation_id": "ru-call", "language": "RU", "channel": "voice call"},
            {"conversation_id": "ru-extra", "language": "RU", "channel": "agent chat"},
        ]

    def test_default_selection_covers_three_languages_and_voice(self):
        selected = select_smoke_dialogs(self.dialogs, 5)
        self.assertEqual({d["language"] for d in selected}, {"RU", "KZ", "EN"})
        self.assertIn("ru-call", [d["conversation_id"] for d in selected])

    def test_explicit_ids_keep_requested_order(self):
        selected = select_smoke_dialogs(self.dialogs, 3, "en-chat,ru-chat,kz-chat")
        self.assertEqual([d["conversation_id"] for d in selected],
                         ["en-chat", "ru-chat", "kz-chat"])

    def test_missing_language_is_rejected(self):
        with self.assertRaises(ValueError):
            select_smoke_dialogs(self.dialogs[:2], 5)

    def test_validator_rejects_invalid_evidence_quote(self):
        dialog = {"transcript": [{"text": "hello"}]}
        evaluation = {"results": [{
            "criterion_id": "greeting", "answer": "yes", "validated": True,
            "evidence": [{"msg_index": 0, "quote": "not present"}],
        }]}
        self.assertTrue(validate_evaluation(evaluation, dialog))


if __name__ == "__main__":
    unittest.main()

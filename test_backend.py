"""Offline tests for the quiz API response validation."""

import json
import unittest

import backend


class GeneratedQuestionsTests(unittest.TestCase):
    def valid_data(self):
        return {
            "tiers": [
                {
                    "ball": ball,
                    "questions": [
                        {
                            "text": [f"Question {index}"],
                            "correct": "B",
                            "explanation": "B javobi to‘g‘ri, chunki bu sinov izohidir.",
                            "options": {"A": "Xato", "B": "To‘g‘ri", "C": "Xato", "D": "Xato"},
                        }
                        for index in range(10)
                    ],
                }
                for ball in (0.9, 1.5, 2.6)
            ]
        }

    def test_validates_thirty_questions_with_explanations(self):
        parsed = backend.validate_questions(self.valid_data())
        self.assertEqual(sum(len(tier["questions"]) for tier in parsed["tiers"]), 30)
        self.assertTrue(parsed["tiers"][0]["questions"][0]["explanation"])

    def test_extracts_fenced_json(self):
        response = {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {
                                "text": "```json\n"
                                + json.dumps(self.valid_data(), ensure_ascii=False)
                                + "\n```"
                            }
                        ]
                    },
                }
            ]
        }
        self.assertEqual(backend.extract_generated_json(response), self.valid_data())

    def test_rejects_question_without_explanation(self):
        data = self.valid_data()
        del data["tiers"][0]["questions"][0]["explanation"]
        with self.assertRaises(backend.BackendError):
            backend.validate_questions(data)

    def test_allows_configured_frontend_origin(self):
        backend.ALLOWED_ORIGINS.add("https://example-quiz.onrender.com")
        self.assertTrue(backend.QuizHandler._is_allowed_origin("https://example-quiz.onrender.com"))
        self.assertFalse(backend.QuizHandler._is_allowed_origin("https://other.example"))


if __name__ == "__main__":
    unittest.main()

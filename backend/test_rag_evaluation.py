import unittest
from unittest.mock import Mock, patch

import httpx
import openai
import requests

from app.rag.citation_validator import validate_citations
from app.rag.generation import LLMGenerationError, generate_answer
from evaluation.evaluate_rag import detect_abstention, evaluate_case


def _groq_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return httpx.Response(status_code, request=request)


class RagEvaluationTests(unittest.TestCase):
    def test_answerable_text_is_not_abstention_when_it_mentions_missing_information(self):
        answer = "The policy requires MFA; the document has no information about travel."
        self.assertFalse(detect_abstention(answer))

    def test_unanswerable_text_is_abstention(self):
        self.assertTrue(
            detect_abstention(
                "I couldn't find relevant evidence in the available documents."
            )
        )

    def test_individual_and_grouped_citations_are_validated(self):
        sources = [{"source_id": "S1"}, {"source_id": "S2"}, {"source_id": "S3"}]
        validation = validate_citations("The answer [S1] and [S2, S3].", sources)
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["valid_citations"], ["S1", "S2", "S3"])

    def test_invalid_citation_id_is_reported(self):
        validation = validate_citations("Unsupported claim [S4].", [{"source_id": "S1"}])
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["invalid_citations"], ["S4"])

    @patch("app.rag.generation.client")
    def test_groq_rate_limit_error_is_classified_without_retrying(self, client):
        client.chat.completions.create.side_effect = openai.RateLimitError(
            "rate limited", response=_groq_response(429), body=None
        )
        with self.assertRaises(LLMGenerationError) as context:
            generate_answer("question", "[S1] evidence")
        self.assertEqual(context.exception.status_code, 429)
        client.chat.completions.create.assert_called_once()

    @patch("app.rag.generation.client")
    def test_groq_authentication_error_is_classified(self, client):
        client.chat.completions.create.side_effect = openai.AuthenticationError(
            "invalid key", response=_groq_response(401), body=None
        )
        with self.assertRaises(LLMGenerationError) as context:
            generate_answer("question", "[S1] evidence")
        self.assertEqual(context.exception.status_code, 401)

    @patch("evaluation.evaluate_rag.time.sleep")
    @patch("evaluation.evaluate_rag.requests.post")
    def test_http_500_is_retried_then_reported(self, post, sleep):
        response = Mock(status_code=500)
        response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error", response=response
        )
        post.return_value = response

        with self.assertRaises(requests.HTTPError):
            evaluate_case({"id": "E500", "query": "question"})

        self.assertEqual(post.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()

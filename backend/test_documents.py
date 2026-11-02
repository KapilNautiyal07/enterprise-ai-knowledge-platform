import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.ask import AskRequest, router as ask_router
from app.api.documents import router as document_router
from app.core.dependencies import get_db
from app.rag.chunker import chunk_text, content_fingerprint
from app.rag.generation import LLMGenerationError, is_summary_request
from app.rag.retrieval import _unique_by_content


def _client(db):
    app = FastAPI()
    app.include_router(document_router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


class DuplicateHandlingTests(unittest.TestCase):
    def test_fingerprint_is_stable_and_content_sensitive(self):
        chunks = chunk_text("Employees must use MFA. " * 100)
        self.assertEqual(content_fingerprint(chunks), content_fingerprint(list(chunks)))
        self.assertNotEqual(content_fingerprint(chunks), content_fingerprint(chunks[:-1]))

    def test_identical_chunks_are_returned_once(self):
        first = SimpleNamespace(content="Passwords need 12 characters.")
        copy = SimpleNamespace(content="Passwords need 12 characters.")
        other = SimpleNamespace(content="MFA is required.")
        results = [(first, "a.pdf", 0.1), (copy, "a (1).pdf", 0.1), (other, "a.pdf", 0.3)]

        unique = _unique_by_content(results, top_k=5)

        self.assertEqual([row[0] for row in unique], [first, other])

    def test_unique_results_respect_top_k(self):
        rows = [(SimpleNamespace(content=str(i)), "a.pdf", 0.1) for i in range(5)]
        self.assertEqual(len(_unique_by_content(rows, top_k=2)), 2)


class AskRequestTests(unittest.TestCase):
    def test_document_ids_are_optional(self):
        self.assertIsNone(AskRequest(query="What is MFA?").document_ids)

    def test_document_ids_must_be_uuids(self):
        document_id = uuid.uuid4()
        request = AskRequest(query="What is MFA?", document_ids=[str(document_id)])
        self.assertEqual(request.document_ids, [document_id])
        with self.assertRaises(ValidationError):
            AskRequest(query="What is MFA?", document_ids=["not-a-uuid"])


class UploadTests(unittest.TestCase):
    @patch("app.api.documents.extract_text", return_value="   ")
    def test_file_without_text_is_rejected_with_a_clear_message(self, _extract):
        db = MagicMock()
        response = _client(db).post(
            "/documents/upload",
            files={"file": ("scan.pdf", b"%PDF-1.4", "application/pdf")},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("readable text", response.json()["detail"])
        db.add.assert_not_called()

    @patch("app.api.documents.ingest_document")
    @patch("app.api.documents.extract_text", return_value="Employees must use MFA.")
    def test_duplicate_upload_reuses_existing_document(self, _extract, ingest):
        existing = SimpleNamespace(
            id=uuid.uuid4(), filename="policy.pdf", file_type=".pdf", created_at=None
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing

        response = _client(db).post(
            "/documents/upload",
            files={"file": ("policy copy.pdf", b"text", "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "duplicate")
        self.assertEqual(response.json()["document_id"], str(existing.id))
        ingest.assert_not_called()

    def test_unsupported_extension_is_rejected(self):
        response = _client(MagicMock()).post(
            "/documents/upload",
            files={"file": ("image.png", b"png", "image/png")},
        )
        self.assertEqual(response.status_code, 400)

    def test_deleting_unknown_document_returns_404(self):
        db = MagicMock()
        db.get.return_value = None
        response = _client(db).delete(f"/documents/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)


class SummaryTests(unittest.TestCase):
    def test_summary_requests_are_detected(self):
        for query in ["Summarize this document", "Give me a summary", "summarise the pdf",
                      "What is this document about?", "key points please", "TL;DR"]:
            self.assertTrue(is_summary_request(query), query)

    def test_specific_questions_are_not_summaries(self):
        for query in ["What is the password policy?", "Which skills does Keshav have?"]:
            self.assertFalse(is_summary_request(query), query)

    @patch("app.rag.retrieval.func")
    def test_long_documents_are_sampled_from_start_to_end(self, _func):
        from app.rag.retrieval import document_chunks

        rows = [(SimpleNamespace(content=str(i)), "doc.pdf") for i in range(40)]
        db = MagicMock()
        db.query.return_value.filter.return_value.scalar.return_value = 40
        db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = rows

        sample = document_chunks(db, [uuid.uuid4()], max_chunks=8, spread=True)
        indexes = [int(item["chunk"].content) for item in sample]

        self.assertEqual(len(indexes), 8)
        self.assertEqual(indexes[0], 0)
        self.assertGreaterEqual(indexes[-1], 35)
        self.assertIsNone(document_chunks(db, [uuid.uuid4()], max_chunks=8))


class StreamingTests(unittest.TestCase):
    def _client(self):
        app = FastAPI()
        app.include_router(ask_router)
        app.dependency_overrides[get_db] = lambda: MagicMock()
        return TestClient(app)

    def _evidence(self):
        chunk = SimpleNamespace(content="Passwords need 12 characters.", chunk_index=0,
                                document_id=uuid.uuid4(), id=uuid.uuid4())
        return [{"chunk": chunk, "filename": "policy.pdf", "reranker_score": 1.0}]

    def _events(self, response):
        return [json.loads(line) for line in response.text.splitlines() if line]

    @patch("app.api.ask.stream_answer", return_value=iter(["Passwords need ", "12 characters [S1]."]))
    @patch("app.api.ask.hybrid_reranked_search")
    def test_answer_is_streamed_then_validated(self, search, _stream):
        search.return_value = self._evidence()

        events = self._events(self._client().post("/ask/stream", json={"query": "Password rules?"}))

        self.assertEqual([e["type"] for e in events], ["meta", "delta", "delta", "done"])
        self.assertEqual(events[0]["documents_used"], ["policy.pdf"])
        self.assertEqual(events[-1]["answer"], "Passwords need 12 characters [S1].")
        self.assertTrue(events[-1]["citation_validation"]["valid"])

    @patch("app.api.ask.stream_answer", side_effect=LLMGenerationError(429, "rate limited"))
    @patch("app.api.ask.hybrid_reranked_search")
    def test_generation_errors_are_reported_in_the_stream(self, search, _stream):
        search.return_value = self._evidence()

        events = self._events(self._client().post("/ask/stream", json={"query": "Password rules?"}))

        self.assertEqual(events[-1], {"type": "error", "status": 429, "detail": "rate limited"})


if __name__ == "__main__":
    unittest.main()

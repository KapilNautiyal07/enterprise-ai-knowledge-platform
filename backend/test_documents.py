import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.ask import AskRequest
from app.api.documents import router as document_router
from app.core.dependencies import get_db
from app.rag.chunker import chunk_text, content_fingerprint
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


if __name__ == "__main__":
    unittest.main()

"""Offline integration checks; external model/backend calls use controlled doubles."""
import io
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

os.environ.update(LLM_PROVIDER="openai_compatible", LLM_BASE_URL="http://127.0.0.1:19999/v1",
                  LLM_API_KEY="integration-test-only", LLM_MODEL="integration-test")

import httpx
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from software_quality_agent.config import get_settings
from software_quality_agent.server import build_app


class MergeIntegration(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{self.directory.name}/agent.sqlite")
        self.env.start()
        get_settings.cache_clear()
        self.client = TestClient(build_app())
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        get_settings.cache_clear()
        self.directory.cleanup()

    def test_original_api_and_shared_page(self):
        for path in ["/api/health", "/api/projects", "/api/database/schema", "/"]:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get("/quality.html").status_code, 404)
        schema = self.client.get("/openapi.json").json()["paths"]
        for path in ["/api/chat", "/api/reports/generate", "/api/database/write", "/api/requirements/extract"]:
            self.assertIn(path, schema)

    def test_pdf_upload_extracts_and_consolidates(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 50 700 Td (The system shall validate passwords and create login sessions.) Tj ET")
        page[NameObject("/Contents")] = stream
        pdf = io.BytesIO()
        writer.write(pdf)
        llm = self.client.app.state.service.llm
        with patch.object(llm, "chat", new=AsyncMock(side_effect=[
            '{"requirements":[{"statement":"Validate passwords"},{"statement":"Create login sessions"}]}',
            '{"requirements":[{"statement":"Authenticate users and create login sessions"}]}',
        ])) as chat:
            response = self.client.post("/api/requirements/extract", files={"file": ("project.pdf", pdf.getvalue(), "application/pdf")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(chat.await_count, 2)
        self.assertEqual(len(response.json()["requirements"]), 1)
        self.assertEqual(response.json()["requirements"][0]["requirement_id"], "REQ-001")

    def test_quality_proxy_preserves_request_and_response(self):
        upstream = httpx.Response(422, json={"code": 10006, "msg": "invalid scope", "data": None})
        with patch("software_quality_agent.server.httpx.AsyncClient") as factory:
            client = factory.return_value.__aenter__.return_value
            client.request = AsyncMock(return_value=upstream)
            response = self.client.post("/api/v1/tlr/projects?tenant_id=local&tag=a&tag=b", json={"name": "integration"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), upstream.json())
        args, kwargs = client.request.call_args
        self.assertEqual(args, ("POST", "http://127.0.0.1:8000/api/v1/tlr/projects"))
        self.assertEqual(kwargs["params"], [("tenant_id", "local"), ("tag", "a"), ("tag", "b")])
        self.assertIn(b'integration', kwargs["content"])

    def test_quality_backend_unavailable_does_not_disable_agent(self):
        with patch("software_quality_agent.server.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value.request = AsyncMock(side_effect=httpx.ConnectError("offline"))
            self.assertEqual(self.client.get("/api/v1/tlr/projects").status_code, 502)
        self.assertEqual(self.client.get("/api/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()

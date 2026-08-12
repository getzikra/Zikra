import importlib
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx


class EmbeddingConfigurationTests(unittest.TestCase):
    def test_embedding_dimension_controls_zero_vector(self):
        from zikra import embed

        try:
            with patch.dict(os.environ, {"ZIKRA_EMBEDDING_DIMENSIONS": "768"}):
                importlib.reload(embed)
                self.assertEqual(embed.embedding_dimensions(), 768)
                self.assertEqual(len(embed.zero_embedding()), 768)
        finally:
            importlib.reload(embed)

    def test_initial_schema_uses_configured_embedding_dimension(self):
        initial_schema = importlib.import_module("zikra.migrations.001_initial_schema")
        try:
            with patch.dict(os.environ, {"ZIKRA_EMBEDDING_DIMENSIONS": "768"}):
                importlib.reload(initial_schema)
                self.assertIn("embedding float[768]", initial_schema.SQL)
        finally:
            importlib.reload(initial_schema)

    def test_embedding_response_dimension_must_match_configuration(self):
        from zikra import embed

        response = httpx.Response(
            200,
            json={"data": [{"embedding": [0.0, 0.0]}]},
            request=httpx.Request("POST", "http://embedding.test/v1/embeddings"),
        )
        client = AsyncMock()
        client.post.return_value = response
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None

        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_API_BASE": "http://embedding.test/v1",
            "ZIKRA_EMBEDDING_DIMENSIONS": "3",
        }), patch.object(httpx, "AsyncClient", return_value=client):
            self.assertIsNone(__import__("asyncio").run(embed.embed("hello")))

    def test_postgres_schema_uses_configured_embedding_dimension(self):
        from zikra import db_postgres

        try:
            with patch.dict(os.environ, {"ZIKRA_EMBEDDING_DIMENSIONS": "768"}):
                importlib.reload(db_postgres)
                self.assertIn("embedding    halfvec(768)", db_postgres._PG_TABLES)
        finally:
            importlib.reload(db_postgres)


if __name__ == "__main__":
    unittest.main()

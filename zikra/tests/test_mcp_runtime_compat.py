"""Guard the MCP runtime API used by the embedded Streamable HTTP server."""
import unittest
from importlib.metadata import version

from zikra import mcp_server


class McpRuntimeCompatibilityTests(unittest.TestCase):
    def test_server_exposes_registered_tools(self):
        self.assertTrue(hasattr(mcp_server.mcp, "list_tools"))
        self.assertEqual(version("mcp"), "1.28.1")


if __name__ == "__main__":
    unittest.main()

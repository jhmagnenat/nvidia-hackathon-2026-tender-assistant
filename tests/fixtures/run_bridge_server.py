"""Test helper: runs src/simap_bridge.py's real Starlette/uvicorn app on a
real local port, with its SimapAdapter pointed at one of the fake stdio MCP
servers in this same directory. Shared by tests/test_simap_bridge.py (via
TestClient, no real socket) callers and tests/adapters/test_simap_bridge_client.py
/ tests/agents/test_search.py (which need a real socket for a real HTTP
client). Never touches NemoClaw — see src/simap_bridge.py's module docstring.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from contextlib import contextmanager
from unittest import mock

import uvicorn

import src.simap_bridge as bridge
from src.adapters.tender_search import REPO_ROOT, SimapAdapter


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def run_bridge_server(fake_server_args: list[str]):
    """Yields the base URL of a real, locally-running bridge server backed
    by the given fake MCP stdio server module args (e.g.
    ["-m", "tests.fixtures.fake_simap_mcp_server"])."""
    port = _free_port()

    def fake_adapter():
        return SimapAdapter(node_command=sys.executable, args=fake_server_args, cwd=str(REPO_ROOT))

    config = uvicorn.Config(bridge.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)

    with mock.patch.object(bridge, "_adapter", fake_adapter):
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("bridge server did not start in time")
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=5)

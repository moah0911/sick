#!/usr/bin/env python3
"""Real demo: fetch_url with SSRF guard and truncation.

Run: uv run python demos/web_research.py
"""
import tempfile
from pathlib import Path
from unittest.mock import Mock

from sick.agent import SickAgent
from sick.tools.web import MAX_URL_BYTES


def main() -> None:
    ws = Path(tempfile.mkdtemp(prefix="sick-web-"))
    agent = SickAgent(workspace=ws)

    # SSRF blocked (no network needed)
    assert "blocked host" in agent.fetch_url("http://localhost:5001/secret")
    assert "blocked host" in agent.fetch_url("http://169.254.169.254/meta")
    assert "credentials not allowed" in agent.fetch_url("http://user:pass@example.com/")

    # non-http rejected
    assert "only http/https" in agent.fetch_url("file:///etc/passwd")

    # successful fetch via mocked urlopen (real logic, no live network)
    import urllib.request

    real_urlopen = urllib.request.urlopen

    def _fake_ok(req, timeout=10):
        class R:
            headers = {"Content-Type": "text/html"}
            def read(self, n): return b"<html>hello world</html>"
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return R()

    urllib.request.urlopen = _fake_ok
    try:
        out = agent.fetch_url("https://example.com/")
        print(out)
        assert "hello world" in out
    finally:
        urllib.request.urlopen = real_urlopen

    # truncation via fake large body
    def _fake_big(req, timeout=10):
        class R:
            headers = {"Content-Type": "text/html"}
            def read(self, n): return b"x" * (MAX_URL_BYTES + 500)
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return R()

    urllib.request.urlopen = _fake_big
    try:
        out = agent.fetch_url("https://example.com/big")
        assert "truncated after" in out
        print("truncation ok")
    finally:
        urllib.request.urlopen = real_urlopen

    print("demo passed: web_research")


if __name__ == "__main__":
    main()

import urllib.error
import urllib.request

from sick.tools.base import Tool


MAX_URL_BYTES = 100_000
URL_TIMEOUT = 10


class FetchUrl(Tool):
    name = "fetch_url"
    description = "Fetch a web page (http/https only) as text, bounded to 100KB"

    def execute(self, url: str) -> str:
        if not str(url).lower().startswith(("http://", "https://")):
            return f"[error: only http/https URLs are allowed: {url}]"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sick-agent/0.1"})
            with urllib.request.urlopen(req, timeout=URL_TIMEOUT) as resp:
                data = resp.read(MAX_URL_BYTES + 1)
        except urllib.error.URLError as e:
            return f"[error fetching URL: {e.reason}]"
        except OSError as e:
            return f"[error fetching URL: {e}]"
        truncated = len(data) > MAX_URL_BYTES
        text = data[:MAX_URL_BYTES].decode("utf-8", errors="replace")
        if truncated:
            text += f"\n[truncated after {MAX_URL_BYTES} bytes]"
        return text
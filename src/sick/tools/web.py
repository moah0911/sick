import ipaddress
import urllib.error
import urllib.parse
import urllib.request

from sick.tools.base import Tool

MAX_URL_BYTES = 100_000
URL_TIMEOUT = 10

_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_BLOCKED_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_blocked_host(host: str) -> bool:
    h = host.lower().strip("[]")
    if h in _BLOCKED_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(h)
        return any(ip in net for net in _BLOCKED_NETS)
    except ValueError:
        # hostname, block metadata service names
        return h in {"metadata.google.internal", "instance-data", "169.254.169.254"}


class FetchUrl(Tool):
    name = "fetch_url"
    description = "Fetch a web page (http/https only) as text, bounded to 100KB"

    def execute(self, url: str) -> str:
        raw = str(url).strip()
        if not raw.lower().startswith(("http://", "https://")):
            return f"[error: only http/https URLs are allowed: {url}]"
        try:
            parsed = urllib.parse.urlparse(raw)
            host = parsed.hostname or ""
            if _is_blocked_host(host):
                return f"[error: blocked host: {host}]"
            # also reject userinfo in url (ssrf via @)
            if parsed.username or parsed.password:
                return f"[error: URL with credentials not allowed: {url}]"
        except Exception:
            pass
        try:
            req = urllib.request.Request(raw, headers={"User-Agent": "sick-agent/0.1"})
            with urllib.request.urlopen(req, timeout=URL_TIMEOUT) as resp:
                ctype = resp.headers.get("Content-Type", "") if hasattr(resp, "headers") else ""
                if ctype and not any(x in ctype.lower() for x in ("text", "html", "json", "xml", "javascript")):
                    return f"[error: unsupported content type: {ctype}]"
                data = resp.read(MAX_URL_BYTES + 1)
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            return f"[error fetching URL: {reason}]"
        except OSError as e:
            return f"[error fetching URL: {e}]"
        truncated = len(data) > MAX_URL_BYTES
        text = data[:MAX_URL_BYTES].decode("utf-8", errors="replace")
        if truncated:
            text += f"\n[truncated after {MAX_URL_BYTES} bytes]"
        return text
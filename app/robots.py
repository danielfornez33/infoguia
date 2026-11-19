import json
import urllib.robotparser as robotparser
from urllib.parse import urlparse

import httpx

from .config import settings
from .redis_client import r

EXTRA_DISALLOW = ("/tienda/",)


def _load(host: str) -> str:
    key = f"robots:{host}"
    cached = r.get(key)
    if cached is not None:
        try:
            return json.loads(cached).get("content", "")
        except Exception:
            pass
    url = f"https://{host}/robots.txt"
    content = ""
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": settings.crawl_user_agent},
            timeout=15,
            follow_redirects=True,
        )
        if response.status_code == 200:
            content = response.text
    except Exception:
        content = ""
    r.setex(key, settings.robots_ttl, json.dumps({"content": content}))
    return content


def can_fetch(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    if any(parsed.path.startswith(prefix) for prefix in EXTRA_DISALLOW):
        return False
    parser = robotparser.RobotFileParser()
    parser.parse(_load(parsed.netloc).splitlines())
    return parser.can_fetch(settings.crawl_user_agent, url)

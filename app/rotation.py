import random
import threading

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


class ProxyRotator:
    def __init__(self, proxies: list[str] | None = None) -> None:
        self._proxies = list(proxies or [])
        self._index = 0
        self._lock = threading.Lock()
        self._failures: dict[str, int] = {}
        self._max_failures = 3

    @property
    def available(self) -> bool:
        return len(self._healthy_proxies) > 0

    @property
    def _healthy_proxies(self) -> list[str]:
        return [p for p in self._proxies if self._failures.get(p, 0) < self._max_failures]

    def get_proxy(self) -> str | None:
        healthy = self._healthy_proxies
        if not healthy:
            return None
        with self._lock:
            proxy = healthy[self._index % len(healthy)]
            self._index += 1
            return proxy

    def report_success(self, proxy: str) -> None:
        with self._lock:
            self._failures.pop(proxy, None)

    def report_failure(self, proxy: str) -> None:
        with self._lock:
            self._failures[proxy] = self._failures.get(proxy, 0) + 1

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._index = 0

    def add_proxy(self, proxy: str) -> None:
        with self._lock:
            if proxy not in self._proxies:
                self._proxies.append(proxy)

    def remove_proxy(self, proxy: str) -> None:
        with self._lock:
            if proxy in self._proxies:
                self._proxies.remove(proxy)
                self._failures.pop(proxy, None)


class UserAgentRotator:
    def __init__(self, custom_agents: list[str] | None = None) -> None:
        self._agents = list(custom_agents or USER_AGENTS)
        self._index = 0
        self._lock = threading.Lock()

    def get_user_agent(self) -> str:
        with self._lock:
            agent = self._agents[self._index % len(self._agents)]
            self._index += 1
            return agent

    def get_random(self) -> str:
        return random.choice(self._agents)

    def add_agent(self, agent: str) -> None:
        with self._lock:
            if agent not in self._agents:
                self._agents.append(agent)


_ACCEPT_PATTERNS = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
]

_SEC_FETCH_NAV = [
    {"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1"},
    {"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-User": "?1"},
    {"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "cross-site", "Sec-Fetch-User": "?1"},
]

_LANG_FRAGMENTS = [
    "es-VE", "es", "en-US", "en", "es-419",
]


def build_browser_headers(user_agent: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}

    if user_agent:
        headers["User-Agent"] = user_agent
    else:
        headers["User-Agent"] = get_ua_rotator().get_random()

    headers["Accept"] = random.choice(_ACCEPT_PATTERNS)

    langs = list(_LANG_FRAGMENTS)
    random.shuffle(langs)
    weights = random.sample([0.9, 0.8, 0.7, 0.6, 0.5], len(langs))
    headers["Accept-Language"] = ",".join(
        f"{lang};q={w:.1f}" if w < 1.0 else lang
        for lang, w in zip(langs, weights, strict=False)
    )

    encodings = ["gzip", "deflate"]
    if random.random() < 0.5:
        encodings.append("br")
    headers["Accept-Encoding"] = ", ".join(encodings)

    if random.random() < 0.7:
        headers["Connection"] = "keep-alive"

    if random.random() < 0.6:
        headers["Upgrade-Insecure-Requests"] = "1"

    sec_fetch = random.choice(_SEC_FETCH_NAV)
    headers.update(sec_fetch)

    cache_choice = random.random()
    if cache_choice < 0.33:
        headers["Cache-Control"] = "max-age=0"
    elif cache_choice < 0.66:
        headers["Cache-Control"] = "no-cache"

    return headers


_rotator: ProxyRotator | None = None
_ua_rotator: UserAgentRotator | None = None
_init_lock = threading.Lock()


def get_proxy_rotator(proxies: list[str] | None = None) -> ProxyRotator:
    global _rotator
    with _init_lock:
        if _rotator is None:
            _rotator = ProxyRotator(proxies)
        return _rotator


def get_ua_rotator(custom_agents: list[str] | None = None) -> UserAgentRotator:
    global _ua_rotator
    with _init_lock:
        if _ua_rotator is None:
            _ua_rotator = UserAgentRotator(custom_agents)
        return _ua_rotator

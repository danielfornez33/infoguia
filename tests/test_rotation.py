from app.rotation import ProxyRotator, UserAgentRotator


def test_proxy_rotator_basic():
    proxies = ["http://proxy1:8080", "http://proxy2:8080", "http://proxy3:8080"]
    rotator = ProxyRotator(proxies)
    assert rotator.available is True
    seen = set()
    for _ in range(6):
        proxy = rotator.get_proxy()
        assert proxy is not None
        seen.add(proxy)
    assert len(seen) == 3


def test_proxy_rotator_failure():
    rotator = ProxyRotator(["http://proxy1:8080"])
    assert rotator.available is True
    proxy = rotator.get_proxy()
    for _ in range(3):
        rotator.report_failure(proxy)
    assert rotator.available is False
    assert rotator.get_proxy() is None


def test_proxy_rotator_recovery():
    rotator = ProxyRotator(["http://proxy1:8080"])
    proxy = rotator.get_proxy()
    for _ in range(3):
        rotator.report_failure(proxy)
    assert rotator.available is False
    rotator.reset()
    assert rotator.available is True
    assert rotator.get_proxy() == "http://proxy1:8080"


def test_proxy_rotator_add_remove():
    rotator = ProxyRotator()
    assert rotator.available is False
    rotator.add_proxy("http://proxy1:8080")
    assert rotator.available is True
    assert rotator.get_proxy() == "http://proxy1:8080"
    rotator.remove_proxy("http://proxy1:8080")
    assert rotator.available is False


def test_proxy_rotator_empty():
    rotator = ProxyRotator()
    assert rotator.available is False
    assert rotator.get_proxy() is None


def test_ua_rotator_basic():
    rotator = UserAgentRotator()
    seen = set()
    for _ in range(16):
        ua = rotator.get_user_agent()
        seen.add(ua)
    assert len(seen) > 1


def test_ua_rotator_custom():
    agents = ["CustomAgent/1.0", "CustomAgent/2.0"]
    rotator = UserAgentRotator(agents)
    seen = set()
    for _ in range(4):
        seen.add(rotator.get_user_agent())
    assert seen == set(agents)


def test_ua_rotator_random():
    rotator = UserAgentRotator()
    ua = rotator.get_random()
    assert isinstance(ua, str)
    assert len(ua) > 0


def test_ua_rotator_add():
    rotator = UserAgentRotator(["Agent/1.0"])
    rotator.add_agent("Agent/2.0")
    seen = set()
    for _ in range(10):
        seen.add(rotator.get_user_agent())
    assert "Agent/2.0" in seen

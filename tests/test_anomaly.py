from app.anomaly import (
    analyze_response,
    detect_captcha,
    detect_empty_page,
    detect_listing_structure,
)

NORMAL_LISTING = """
<html><body>
<div class="box-announce dimensions-box-ads">
  <a class="ads-text-link" href="/is.asp?emp=x&clte=123" data-company="123">Empresa</a>
  <section aria-labelledby="direccion-empresa0"><span>Caracas</span></section>
  <section aria-labelledby="telefonos-empresa0"><span class="telefono-desktop">02121234567</span></section>
</div>
</body></html>
"""

CAPTCHA_PAGE = """
<html><body>
<div class="g-recaptcha" data-sitekey="abc123"></div>
<p>Por favor verifique que no es un robot</p>
</body></html>
"""

CLOUDFLARE_CHALLENGE = """
<html><body>
<div id="challenge-running">Checking your browser before accessing</div>
<p>Just a moment...</p>
</body></html>
"""

EMPTY_PAGE = """
<html><body>
<h1>404</h1>
<p>Page not found</p>
</body></html>
"""

BROKEN_STRUCTURE = """
<html><body>
<div class="something-else">
  <p>This page has completely different structure</p>
</div>
</body></html>
"""


def test_detect_captcha_google():
    detected, ctype = detect_captcha(CAPTCHA_PAGE)
    assert detected is True
    assert ctype == "g-recaptcha"


def test_detect_captcha_cloudflare():
    detected, ctype = detect_captcha(CLOUDFLARE_CHALLENGE)
    assert detected is True
    assert "just a moment" in ctype or "checking your browser" in ctype


def test_detect_captcha_none():
    detected, ctype = detect_captcha(NORMAL_LISTING)
    assert detected is False
    assert ctype == ""


def test_detect_empty_page_short():
    assert detect_empty_page("") is True
    assert detect_empty_page("short") is True


def test_detect_empty_page_404():
    assert detect_empty_page(EMPTY_PAGE) is True


def test_detect_empty_page_normal():
    assert detect_empty_page(NORMAL_LISTING) is False


def test_detect_listing_structure_ok():
    changed, missing = detect_listing_structure(NORMAL_LISTING)
    assert changed is False
    assert len(missing) == 0


def test_detect_listing_structure_broken():
    changed, missing = detect_listing_structure(BROKEN_STRUCTURE)
    assert changed is True
    assert len(missing) > 0


def test_analyze_response_normal():
    result = analyze_response(NORMAL_LISTING, "listing")
    assert result.is_anomalous is False
    assert result.captcha_detected is False
    assert result.empty_page is False
    assert result.structure_changed is False


def test_analyze_response_captcha():
    result = analyze_response(CAPTCHA_PAGE, "listing")
    assert result.is_anomalous is True
    assert result.captcha_detected is True
    assert "captcha" in result.reason.lower()


def test_analyze_response_broken_structure():
    result = analyze_response(BROKEN_STRUCTURE, "listing")
    assert result.is_anomalous is True
    assert result.structure_changed is True


def test_analyze_response_empty():
    result = analyze_response(EMPTY_PAGE, "listing")
    assert result.is_anomalous is True
    assert result.empty_page is True



from app.adapters import get_adapter, get_adapter_for_url
from app.parsers import parse_listing, parse_profile, parse_store
from app.rotation import build_browser_headers

LISTING_HTML = """
<html><body>
<div class="box-announce dimensions-box-ads">
  <a class="ads-text-link" href="/is.asp?emp=empresa-x&amp;clte=123&amp;ciud=41" data-company="123">Empresa X</a>
  <img class="btn-verified-customer" src="check.webp">
  <section aria-labelledby="direccion-empresa0"><span>Sector A, Baruta, Caracas</span></section>
  <section aria-labelledby="telefonos-empresa0">
    <span class="telefono-desktop">(0212)123.4567</span>
  </section>
  <a class="whatsapp-click-stats" data-phone-number="(0414)123.4567" href="https://web.whatsapp.com/send?phone=5804141234567"></a>
  <span class="star-rating-precise" style="--rating: 80%;"></span>
  <a href="/shop/stores/empresa-x">tienda</a>
</div>
<div class="pagination">
  <a class="other-pages" href="/ct.asp?key=x&amp;cat=738&amp;ciud=41&amp;p=2">2</a>
</div>
</body></html>
"""

PROFILE_HTML = """
<html><head><meta name="description" content="Empresa de repuestos"></head><body>
<h1 id="companyName">Empresa X</h1>
<img class="btn-verified-customer" src="check.webp">
<a data-branch-idbranch="0"
   data-branch-urbanization="Sector A"
   data-branch-address="Calle 1, Baruta, Caracas"
   data-branch-phone="(0212)123.4567"
   data-branch-whatsapp="(0414)123.4567"
   data-branch-email="contacto@empresa.com"></a>
<a class="social-network-stats" href="https://www.instagram.com/empresa"></a>
<a href="/shop/stores/empresa-x">InfoShop</a>
</body></html>
"""

STORE_HTML = """
<html><body>
<h2 class="fs-text-1">Empresa X</h2>
<div class="ps-product">
  <a href="/shop/products/filtro"><img src="/filtro.webp"></a>
  <a class="ps-product__title" href="/shop/products/filtro">Filtro de aceite</a>
  <span class="ps-product__price">$10</span>
</div>
</body></html>
"""

CAPTCHA_HTML = """
<html><body>
<div class="g-recaptcha" data-sitekey="abc123"></div>
<p>Por favor verifique que no es un robot</p>
</body></html>
"""


def test_integration_listing_to_profile_flow():
    listing_url = "https://infoguia.com/ct.asp?key=x&cat=738&ciud=41"
    listing_data = parse_listing(LISTING_HTML, listing_url)

    assert len(listing_data["companies"]) == 1
    company = listing_data["companies"][0]
    assert company["clte"] == "123"
    assert company["name"] == "Empresa X"
    assert company["profile_url"].endswith("/is.asp?emp=empresa-x&clte=123&ciud=41")
    assert company["store_url"].endswith("/shop/stores/empresa-x")
    assert len(listing_data["next_pages"]) == 1

    profile_url = company["profile_url"]
    profile_data = parse_profile(PROFILE_HTML, profile_url)

    assert profile_data["name"] == "Empresa X"
    assert len(profile_data["branches"]) == 1
    branch = profile_data["branches"][0]
    assert branch["email"] == "contacto@empresa.com"
    assert branch["city"] == "Caracas"
    assert len(profile_data["socials"]) == 1
    assert profile_data["socials"][0]["network"] == "instagram"


def test_integration_listing_to_store_flow():
    listing_url = "https://infoguia.com/ct.asp?key=x&cat=738&ciud=41"
    listing_data = parse_listing(LISTING_HTML, listing_url)
    company = listing_data["companies"][0]

    store_url = company["store_url"]
    store_data = parse_store(STORE_HTML, store_url)

    assert store_data["name"] == "Empresa X"
    assert len(store_data["products"]) == 1
    assert store_data["products"][0]["name"] == "Filtro de aceite"
    assert store_data["products"][0]["price"] == "$10"


def test_integration_adapter_detect_kind():
    adapter = get_adapter("infoguia.com")

    assert adapter.detect_kind("https://infoguia.com/ct.asp?key=x&cat=738") == "listing"
    assert adapter.detect_kind("https://infoguia.com/is.asp?clte=123") == "profile"
    assert adapter.detect_kind("https://infoguia.com/shop/stores/empresa-x") == "store"


def test_integration_adapter_for_url():
    adapter = get_adapter_for_url("https://infoguia.com/ct.asp?key=x")
    assert adapter.domain == "infoguia.com"

    adapter_www = get_adapter_for_url("https://www.infoguia.com/ct.asp?key=x")
    assert adapter_www.domain == "infoguia.com"


def test_integration_adapter_unknown_domain():
    import pytest
    with pytest.raises(ValueError, match="No adapter"):
        get_adapter("unknown.com")
    with pytest.raises(ValueError, match="No adapter"):
        get_adapter_for_url("https://unknown.com/page")


def test_integration_adapter_parse_listing():
    adapter = get_adapter("infoguia.com")
    url = "https://infoguia.com/ct.asp?key=x&cat=738&ciud=41"
    data = adapter.parse_listing(LISTING_HTML, url)
    assert len(data["companies"]) == 1
    assert data["companies"][0]["clte"] == "123"


def test_integration_adapter_parse_profile():
    adapter = get_adapter("infoguia.com")
    url = "https://infoguia.com/is.asp?clte=123&ciud=41"
    data = adapter.parse_profile(PROFILE_HTML, url)
    assert data["name"] == "Empresa X"
    assert len(data["branches"]) == 1


def test_integration_adapter_get_listing_urls():
    adapter = get_adapter("infoguia.com")
    url = "https://infoguia.com/ct.asp?key=x&cat=738&ciud=41"
    urls = adapter.get_listing_urls(LISTING_HTML, url)
    assert len(urls) == 1
    assert "p=2" in urls[0]


def test_integration_captcha_detection():
    from app.anomaly import analyze_response

    result = analyze_response(CAPTCHA_HTML, "listing")
    assert result.is_anomalous is True
    assert result.captcha_detected is True


def test_integration_browser_headers_variation():
    headers_1 = build_browser_headers(user_agent="TestAgent/1.0")
    build_browser_headers(user_agent="TestAgent/1.0")

    assert headers_1["User-Agent"] == "TestAgent/1.0"
    assert "Accept" in headers_1
    assert "Accept-Language" in headers_1
    assert "Accept-Encoding" in headers_1
    assert "Sec-Fetch-Dest" in headers_1
    assert "Sec-Fetch-Mode" in headers_1

    all_headers = [build_browser_headers(user_agent="TestAgent/1.0") for _ in range(20)]
    accept_values = {h["Accept"] for h in all_headers}
    assert len(accept_values) >= 2


def test_integration_browser_headers_required_fields():
    headers = build_browser_headers(user_agent="TestAgent/1.0")

    required = {"User-Agent", "Accept", "Accept-Language", "Accept-Encoding",
                "Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-Site"}
    for field in required:
        assert field in headers, f"Missing required header: {field}"


def test_integration_full_scrape_pipeline():
    listing_url = "https://infoguia.com/ct.asp?key=repuestos&cat=738&ciud=41"
    adapter = get_adapter_for_url(listing_url)

    assert adapter.detect_kind(listing_url) == "listing"

    listing_data = adapter.parse_listing(LISTING_HTML, listing_url)
    assert len(listing_data["companies"]) == 1

    company = listing_data["companies"][0]
    profile_url = adapter.get_company_profile_url(company)
    assert profile_url

    profile_data = adapter.parse_profile(PROFILE_HTML, profile_url)
    assert profile_data["name"] == "Empresa X"
    assert len(profile_data["branches"]) >= 1

    store_url = adapter.get_company_store_url(company)
    if store_url:
        store_data = adapter.parse_store(STORE_HTML, store_url)
        assert len(store_data["products"]) >= 0

    next_pages = adapter.get_listing_urls(LISTING_HTML, listing_url)
    assert len(next_pages) == 1
    assert adapter.detect_kind(next_pages[0]) == "listing"

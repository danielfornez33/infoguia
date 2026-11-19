from app.parsers import (
    normalize_name,
    normalize_phone,
    normalize_price,
    parse_listing,
    parse_profile,
    parse_schedule_text,
    parse_store,
    split_phones,
)

LISTING_HTML = """
<html><body>
<div class="box-announce dimensions-box-ads">
  <a class="ads-text-link" href="/is.asp?emp=empresa-x&amp;clte=123&amp;ciud=41" data-company="123">Empresa X</a>
  <img class="btn-verified-customer" src="check.webp">
  <section aria-labelledby="direccion-empresa0"><span>Sector A, Baruta, Caracas</span><span>(+1 ubicación)</span></section>
  <section aria-labelledby="horarios-empresa0"><span>Lun. a Vie. 08:00 am a 05:00 pm</span></section>
  <section aria-labelledby="telefonos-empresa0">
    <span class="telefono-desktop">(0212)123.4567</span>
    <span class="telefono-desktop">(0414)123.4567</span>
  </section>
  <a class="whatsapp-click-stats" data-phone-number="(0414)123.4567" href="https://web.whatsapp.com/send?phone=5804141234567"></a>
  <span class="star-rating-precise" style="--rating: 80%;"></span>
  <p class="desc">Descripción de prueba</p>
  <a href="/shop/stores/empresa-x">tienda</a>
</div>
<div class="pagination">
  <a class="other-pages" href="/ct.asp?key=x&amp;cat=738&amp;ciud=41&amp;p=2">2</a>
</div>
<a href="/ct.asp?key=otra&amp;cat=999&amp;ciud=41" title="Otra categoría">Otra</a>
</body></html>
"""

LISTING_FALLBACK_HTML = """
<html><body>
<div class="box-announce">
  <a href="/is.asp?emp=empresa-y&amp;clte=456&amp;ciud=41" data-company="456">Empresa Y</a>
  <div class="company-address">Av. Principal, Chacao, Caracas</div>
  <div class="company-phone"><a href="tel:+582129876543">(0212)987.6543</a></div>
  <a href="https://wa.me/584141234567">WhatsApp</a>
  <div class="rating" data-rating="75"></div>
  <div class="verified-badge">Verificado</div>
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
   data-branch-phone="(0212)123.4567 (0414)123.4567"
   data-branch-whatsapp="(0414)123.4567"
   data-branch-email="Contacto@Empresa.COM"></a>
<a class="social-network-stats" href="https://www.instagram.com/empresa"></a>
<a href="/ct.asp?key=x&amp;cat=738&amp;ciud=41" title="Repuestos">Repuestos</a>
<a href="/shop/stores/empresa-x">InfoShop</a>
</body></html>
"""

PROFILE_ENRICHED_HTML = """
<html><head><meta name="description" content="Tienda de repuestos premium">
<script type="application/ld+json">{"@type": "LocalBusiness", "name": "Empresa Z"}</script>
</head><body>
<h1 id="companyName">Empresa Z</h1>
<a data-branch-idbranch="0"
   data-branch-address="Av. Francisco de Miranda, Chacao, Caracas"
   data-branch-phone="(0212)555.1234"
   data-branch-whatsapp="(0412)555.5678"
   data-branch-email="info@empresaZ.com"></a>
<a data-branch-idbranch="1"
   data-branch-address="C/C Sambil, Planta Baja, Caracas"
   data-branch-phone="(0212)555.9999"></a>
<a href="https://www.instagram.com/empresaz">Instagram</a>
<a href="https://www.facebook.com/empresaz">Facebook</a>
<section aria-labelledby="horarios-empresa0">
  <span>Lunes a Viernes 8:00 am - 6:00 pm, Sábado 9:00 am - 1:00 pm, Domingo cerrado</span>
</section>
<article class="pr-card">
  <div class="pr-card-title">Filtro de aceite premium</div>
  <img data-src="/filtro_premium.webp" src="/placeholder.webp">
  <a href="/shop/products/filtro-premium"></a>
</article>
<div class="ps-product" data-sku="PS-001">
  <a href="/shop/products/bomba-freno"><img src="/bomba.webp"></a>
  <a class="ps-product__title" href="/shop/products/bomba-freno">Bomba de freno</a>
  <span class="ps-product__price">$25.50</span>
  <span class="availability">Disponible</span>
</div>
<a href="/shop/stores/empresa-z">Tienda</a>
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
<article class="pr-card">
  <div class="pr-card-title">Bomba de freno</div>
  <img src="/bomba.webp">
  <a href="/shop/products/bomba"></a>
</article>
</body></html>
"""

STORE_ENRICHED_HTML = """
<html><body>
<h2 class="fs-text-1">Tienda Premium</h2>
<div class="ps-product" data-sku="FIL-001">
  <a href="/shop/products/filtro"><img data-src="/filtro.webp" src="/placeholder.webp"></a>
  <a class="ps-product__title" href="/shop/products/filtro">Filtro de aceite premium</a>
  <span class="ps-product__price">Bs. 250.00</span>
  <span class="product-description">Filtro de alta calidad</span>
  <span class="availability">Disponible</span>
</div>
<article class="pr-card">
  <div class="pr-card-title">Bomba de freno</div>
  <img data-lazy-src="/bomba.webp" src="/placeholder.webp">
  <a href="/shop/products/bomba"></a>
  <span class="price">$15.00</span>
</article>
</body></html>
"""


def test_normalize_phone():
    assert normalize_phone("(0212)123.4567") == "+582121234567"
    assert normalize_phone("(0414)123.4567") == "+584141234567"
    assert normalize_phone("5804141234567") == "+584141234567"
    assert normalize_phone("+58 414 1234567") == "+584141234567"
    assert normalize_phone("0212-123-4567 Ext. 350") == "+582121234567"


def test_split_phones():
    value = "(0212)123.4567 (0414)123.4567 (0212)903.8711 Ext. 350/351/353"
    assert split_phones(value) == ["+582121234567", "+584141234567", "+582129038711"]


def test_normalize_name():
    assert normalize_name("Motores La Trinidad - Repuestos") == "motores la trinidad repuestos"


def test_normalize_price():
    assert normalize_price("$10.50") == "$10.50"
    assert normalize_price("Bs. 250.000") == "Bs. 250.000"
    assert normalize_price("Precio: $15.00 USD") == "$15.00"


def test_parse_schedule_text():
    result = parse_schedule_text("Lunes a Viernes 8:00 am - 6:00 pm")
    assert len(result["days"]) > 0
    day = next((d for d in result["days"] if d["day"] == "monday"), None)
    assert day is not None
    assert "8:00 am" in day["open"].lower()

    result_247 = parse_schedule_text("Abierto 24/7")
    assert result_247["twenty_four_seven"] is True

    result_closed = parse_schedule_text("Domingo cerrado")
    dom = next((d for d in result_closed["days"] if d["day"] == "sunday"), None)
    assert dom is not None
    assert dom["is_closed"] is True


def test_parse_listing():
    data = parse_listing(LISTING_HTML, "https://infoguia.com/ct.asp?key=x&cat=738&ciud=41")
    assert len(data["companies"]) == 1
    company = data["companies"][0]
    assert company["clte"] == "123"
    assert company["name"] == "Empresa X"
    assert company["address"] == "Sector A, Baruta, Caracas"
    assert company["city"] == "Caracas"
    assert company["verified"] is True
    assert company["rating_pct"] == 80.0
    assert company["cat_id"] == "738"
    assert "+582121234567" in company["phones"]
    assert company["whatsapp"] == ["+584141234567"]
    assert data["next_pages"] == ["https://infoguia.com/ct.asp?key=x&cat=738&ciud=41&p=2"]
    assert any(item["cat_id"] == "999" for item in data["categories"])


def test_parse_listing_fallback():
    data = parse_listing(LISTING_FALLBACK_HTML, "https://infoguia.com/ct.asp?key=x&cat=738&ciud=41")
    assert len(data["companies"]) == 1
    company = data["companies"][0]
    assert company["clte"] == "456"
    assert company["name"] == "Empresa Y"
    assert company["address"] == "Av. Principal, Chacao, Caracas"
    assert company["city"] == "Caracas"
    assert company["verified"] is True
    assert "+582129876543" in company["phones"]
    assert "+584141234567" in company["whatsapp"]


def test_parse_profile():
    data = parse_profile(PROFILE_HTML, "https://infoguia.com/is.asp?emp=empresa-x&clte=123&ciud=41")
    assert data["name"] == "Empresa X"
    assert data["verified"] is True
    assert data["description"] == "Empresa de repuestos"
    assert len(data["branches"]) == 1
    branch = data["branches"][0]
    assert branch["branch_key"] == "0"
    assert branch["email"] == "contacto@empresa.com"
    assert branch["city"] == "Caracas"
    types = {contact["type"] for contact in branch["contacts"]}
    assert types == {"phone", "whatsapp", "email"}
    assert data["socials"][0]["network"] == "instagram"
    assert data["store_url"].endswith("/shop/stores/empresa-x")


def test_parse_profile_enriched():
    data = parse_profile(PROFILE_ENRICHED_HTML, "https://infoguia.com/is.asp?emp=empresa-z&clte=789&ciud=41")
    assert data["name"] == "Empresa Z"
    assert data["description"] == "Tienda de repuestos premium"
    assert len(data["branches"]) == 2
    branch_0 = next(b for b in data["branches"] if b["branch_key"] == "0")
    branch_1 = next(b for b in data["branches"] if b["branch_key"] == "1")
    assert branch_0["city"] == "Caracas"
    assert branch_1["city"] == "Caracas"
    assert branch_0["email"] == "info@empresaz.com"
    assert len(data["socials"]) == 2
    networks = {s["network"] for s in data["socials"]}
    assert "instagram" in networks
    assert "facebook" in networks
    assert len(data["products"]) == 2
    product_names = {p["name"] for p in data["products"]}
    assert "Filtro de aceite premium" in product_names
    assert "Bomba de freno" in product_names
    bomba = next(p for p in data["products"] if p["name"] == "Bomba de freno")
    assert bomba["price"] == "$25.50"
    assert bomba["sku"] == "PS-001"
    assert bomba["availability"] == "in_stock"


def test_parse_store():
    data = parse_store(STORE_HTML, "https://infoguia.com/shop/stores/empresa-x")
    assert len(data["products"]) == 2
    names = {product["name"] for product in data["products"]}
    assert names == {"Filtro de aceite", "Bomba de freno"}


def test_parse_store_enriched():
    data = parse_store(STORE_ENRICHED_HTML, "https://infoguia.com/shop/stores/tienda-premium")
    assert len(data["products"]) == 2
    filtro = next(p for p in data["products"] if "Filtro" in p["name"])
    assert filtro["sku"] == "FIL-001"
    assert filtro["image_url"] == "/filtro.webp"
    assert filtro["description"] == "Filtro de alta calidad"
    assert filtro["availability"] == "in_stock"
    bomba = next(p for p in data["products"] if "Bomba" in p["name"])
    assert bomba["price"] == "$15.00"
    assert bomba["image_url"] == "/bomba.webp"

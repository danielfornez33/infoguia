import pytest
from app.schemas import (
    Branch,
    Category,
    Company,
    Contact,
    ListingData,
    Product,
    ProfileData,
    Social,
    StoreData,
    StructuredSchedule,
)
from pydantic import ValidationError


def test_contact_valid():
    c = Contact(type="phone", value="+584141234567")
    assert c.type == "phone"
    assert c.value == "+584141234567"


def test_contact_empty_value():
    with pytest.raises(ValidationError):
        Contact(type="phone", value="")


def test_branch_valid():
    b = Branch(branch_key="0", address="Av. Principal", city="Caracas")
    assert b.branch_key == "0"
    assert b.city == "Caracas"


def test_branch_defaults():
    b = Branch()
    assert b.branch_key == "0"
    assert b.address == ""


def test_social_valid():
    s = Social(network="instagram", url="https://instagram.com/user")
    assert s.network == "instagram"
    assert s.url.startswith("https")


def test_social_invalid_url():
    with pytest.raises(ValidationError):
        Social(network="instagram", url="not-a-url")


def test_category_valid():
    c = Category(cat_id="738", name="Repuestos")
    assert c.cat_id == "738"
    assert c.name == "Repuestos"


def test_product_valid():
    p = Product(name="Filtro", price="$10", sku="FIL-001", availability="in_stock")
    assert p.name == "Filtro"
    assert p.sku == "FIL-001"


def test_product_defaults():
    p = Product(name="Filtro")
    assert p.price == ""
    assert p.sku == ""
    assert p.availability == ""


def test_company_valid():
    c = Company(
        clte="123",
        name="Empresa X",
        profile_url="https://infoguia.com/is.asp?clte=123",
        phones=["+582121234567"],
        whatsapp=["+584141234567"],
        verified=True,
        rating_pct=80.0,
    )
    assert c.clte == "123"
    assert c.rating_pct == 80.0
    assert len(c.phones) == 1


def test_company_minimal():
    c = Company(clte="456", name="Empresa Y", profile_url="https://infoguia.com/is.asp?clte=456")
    assert c.verified is False
    assert c.rating_pct is None
    assert c.phones == []


def test_listing_data():
    data = ListingData(
        companies=[
            Company(clte="1", name="E1", profile_url="https://infoguia.com/is.asp?clte=1"),
        ],
        next_pages=["https://infoguia.com/ct.asp?p=2"],
        categories=[Category(cat_id="738", name="Repuestos")],
    )
    assert len(data.companies) == 1
    assert len(data.next_pages) == 1
    assert len(data.categories) == 1


def test_structured_schedule():
    s = StructuredSchedule(
        days=[
            {"day": "monday", "open": "8:00 am", "close": "6:00 pm"},
            {"day": "sunday", "is_closed": True},
        ],
        twenty_four_seven=False,
    )
    assert len(s.days) == 2
    assert s.days[1].is_closed is True


def test_profile_data():
    data = ProfileData(
        name="Empresa X",
        description="Descripción",
        verified=True,
        branches=[Branch(branch_key="0", city="Caracas")],
        socials=[Social(network="instagram", url="https://instagram.com/user")],
        products=[Product(name="Filtro", price="$10")],
    )
    assert data.name == "Empresa X"
    assert len(data.branches) == 1
    assert len(data.socials) == 1
    assert len(data.products) == 1


def test_store_data():
    data = StoreData(
        name="Tienda X",
        products=[Product(name="Filtro"), Product(name="Bomba")],
    )
    assert data.name == "Tienda X"
    assert len(data.products) == 2

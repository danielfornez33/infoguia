from typing import Literal

from pydantic import BaseModel, field_validator


class Contact(BaseModel):
    type: Literal["phone", "whatsapp", "email"]
    value: str

    @field_validator("value")
    @classmethod
    def value_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("contact value cannot be empty")
        return v.strip()


class Branch(BaseModel):
    branch_key: str = "0"
    urbanization: str = ""
    address: str = ""
    city: str = ""
    phones: str = ""
    whatsapp: str = ""
    email: str = ""
    contacts: list[Contact] = []


class Social(BaseModel):
    network: str
    url: str

    @field_validator("url")
    @classmethod
    def url_valid(cls, v: str) -> str:
        if not v or not v.startswith("http"):
            raise ValueError("social url must be valid")
        return v


class Category(BaseModel):
    cat_id: str
    name: str


class Product(BaseModel):
    name: str
    price: str = ""
    image_url: str = ""
    url: str = ""
    sku: str = ""
    description: str = ""
    availability: str = ""


class Company(BaseModel):
    clte: str
    name: str
    profile_url: str
    address: str = ""
    city: str = ""
    schedule: str = ""
    phones: list[str] = []
    whatsapp: list[str] = []
    contacts: list[Contact] = []
    rating_pct: float | None = None
    verified: bool = False
    description: str = ""
    store_url: str = ""
    cat_id: str | None = None


class ScheduleDay(BaseModel):
    day: str
    open: str = ""
    close: str = ""
    is_closed: bool = False


class StructuredSchedule(BaseModel):
    days: list[ScheduleDay] = []
    twenty_four_seven: bool = False
    raw_text: str = ""


class ListingData(BaseModel):
    companies: list[Company] = []
    next_pages: list[str] = []
    discovered: list[str] = []
    categories: list[Category] = []


class ProfileData(BaseModel):
    name: str = ""
    description: str = ""
    verified: bool = False
    rating_pct: float | None = None
    store_url: str = ""
    branches: list[Branch] = []
    socials: list[Social] = []
    categories: list[Category] = []
    products: list[Product] = []
    schedule: StructuredSchedule | None = None


class StoreData(BaseModel):
    name: str = ""
    products: list[Product] = []


class ParseResult(BaseModel):
    success: bool = True
    data: ListingData | ProfileData | StoreData | None = None
    errors: list[str] = []
    warnings: list[str] = []
    structure_changed: bool = False

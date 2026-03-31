from pydantic import BaseModel, Field, ConfigDict
from typing import List


# --- INVOICE SCHEMAS ---

class InvoiceItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    description: str = Field(default="")
    hs_code: str = Field(default="")
    quantity: str = Field(default="")
    unit_price: str = Field(default="")
    amount: str = Field(default="")


class InvoiceTotals(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_qty: str = Field(default="0")
    total_amount: str = Field(default="0")
    gross_weight: str = Field(default="0")
    net_weight: str = Field(default="0")
    cbm: str = Field(default="0")
    cartons: str = Field(default="0")


class InvoiceSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    invoice_number: str = Field(default="")
    invoice_date: str = Field(default="")
    po_no: str = Field(default="")
    buyer: str = Field(default="")
    consignee: str = Field(default="")
    items: List[InvoiceItem] = Field(default_factory=list)
    totals: InvoiceTotals = Field(default_factory=InvoiceTotals)


# --- PACKING LIST SCHEMAS ---

class PackingWeights(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    gross_weight: str = Field(default="0")
    net_weight: str = Field(default="0")
    volume: str = Field(default="0")


class PackingSizes(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    XS: int = Field(default=0)
    S: int = Field(default=0)
    M: int = Field(default=0)
    L: int = Field(default=0)
    XL: int = Field(default=0)
    XXL: int = Field(default=0)
    XXXL: int = Field(default=0, alias="3XL")
    XXXXL: int = Field(default=0, alias="4XL")


class PackingListSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    invoice_number: str = Field(default="")
    po_no: str = Field(default="")
    total_cartons: str = Field(default="0")
    dimensions: str = Field(default="")
    sizes: PackingSizes = Field(default_factory=PackingSizes)
    weights: PackingWeights = Field(default_factory=PackingWeights)

import json
from openai import AsyncOpenAI
from schemas import InvoiceSchema, PackingListSchema
from config import OPENAI_API_KEY

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

_CLASSIFICATION_PROMPT = """
You are a document classifier. Read the OCR text and determine whether it is a
Commercial Invoice or a Packing List.

Return ONLY a JSON object: {{"document_type": "invoice"}} or {{"document_type": "packing_list"}}
or {{"document_type": "unknown"}}.

OCR TEXT (first 2000 chars):
{text}
"""

_INVOICE_PROMPT = """
You are an expert data entry assistant for trade documents.
Extract data from the OCR text below into the required JSON schema.

FIELD MAPPING RULES:
- invoice_number: the main invoice/reference number (e.g. "INV-001", "SFA-1159/25-26")
- invoice_date: date on the invoice (ISO format preferred, e.g. "2026-03-11")
- po_no: purchase order number
- buyer: company or person buying the goods
- consignee: company or person receiving the goods
- items[].description: product/goods description
- items[].hs_code: Harmonised System code (tariff code)
- items[].quantity: quantity as a string number
- items[].unit_price: unit price as a string number
- items[].amount: line total as a string number
- totals.total_qty: total quantity across all items
- totals.total_amount: grand total value
- totals.gross_weight: gross weight (look for "Gross Weight", "G.W.", "Poids BRUT")
- totals.net_weight: net weight (look for "Net Weight", "N.W.", "Poids NET")
- totals.cbm: cubic metres / volume
- totals.cartons: total number of cartons/boxes

If a field is not present leave it as "" or "0". Do NOT invent data.

OCR TEXT:
{text}
"""

_PACKING_PROMPT = """
You are an expert data entry assistant for trade documents.
Extract data from the OCR text below into the required JSON schema.

FIELD MAPPING RULES:
- invoice_number: the shipment/invoice reference (e.g. "SFA-1159/25-26"). Remove spaces around "/".
- po_no: look for "PO Number" — it is the numeric code immediately after (e.g. "516247")
- total_cartons: look for "Total number of standard cartons" — the integer directly after it
- dimensions: look for "External dimensions of cartons in mm" — value is like "59*39*40"
- sizes.XS/S/M/L/XL/XXL/3XL/4XL: use the row labelled "Total pcs assorted+std /size" or
  "Total pcs assorted / size". The columns in order are XS, S, M, L, XL, XXL, 3XL, 4XL, TOTAL.
  Map each numeric value to its size column. Return as integers (not the TOTAL column).
- weights.gross_weight: line containing "Poids BRUT" or "Gross Weight" — extract the numeric value only
- weights.net_weight: line containing "Poids NET" or "Net Weight" — extract the numeric value only
- weights.volume: line containing "VOLUME (m3)" or "CBM" — extract the numeric value only

Return all numeric weight/volume fields as strings (e.g. "852.00"). Return total_cartons as a string integer.
If a field is not present leave it as "" or "0". Do NOT invent data.

OCR TEXT:
{text}
"""


async def classify_and_extract(raw_ocr_text: str) -> tuple[str, dict]:
    """
    Classify the document then extract structured data using OpenAI Structured Outputs.

    Returns:
        doc_type  — "invoice" | "packing_list"
        data_dict — extracted fields as a plain dict (alias keys for sizes)
    """
    # --- Step 1: Classification ---
    cls_response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": _CLASSIFICATION_PROMPT.format(text=raw_ocr_text[:2000]),
            }
        ],
        response_format={"type": "json_object"},
    )
    doc_type = (
        json.loads(cls_response.choices[0].message.content)
        .get("document_type", "unknown")
        .lower()
    )

    if doc_type not in ("invoice", "packing_list"):
        raise ValueError(
            f"Document classified as '{doc_type}' — must be invoice or packing_list."
        )

    # --- Step 2: Structured extraction ---
    if doc_type == "invoice":
        prompt = _INVOICE_PROMPT.format(text=raw_ocr_text)
        TargetSchema = InvoiceSchema
    else:
        prompt = _PACKING_PROMPT.format(text=raw_ocr_text)
        TargetSchema = PackingListSchema

    extract_response = await client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format=TargetSchema,
    )

    parsed_model = extract_response.choices[0].message.parsed
    # by_alias=True outputs "3XL" / "4XL" instead of "XXXL" / "XXXXL"
    data_dict = parsed_model.model_dump(by_alias=True)

    return doc_type, data_dict

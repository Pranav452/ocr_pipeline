"""
Validation layer — runs after LLM extraction, before DB insert.
Returns a list of human-readable warning strings.
An empty list means the document passed all checks.
Warnings do NOT block insertion; they are surfaced in the UI as amber notices.
"""


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value or default))
    except (ValueError, TypeError):
        return default


def validate_invoice(data: dict) -> list[str]:
    warnings: list[str] = []

    if not data.get("invoice_number"):
        warnings.append("Invoice number is missing.")
    if not data.get("buyer"):
        warnings.append("Buyer name is missing.")
    if not data.get("invoice_date"):
        warnings.append("Invoice date is missing.")

    items = data.get("items", [])
    if not items:
        warnings.append("No line items were extracted.")

    totals = data.get("totals", {})
    declared_total_qty = _safe_float(totals.get("total_qty"))
    declared_total_amount = _safe_float(totals.get("total_amount"))

    # Cross-check: sum of item quantities vs declared total
    if items:
        sum_qty = sum(_safe_float(item.get("quantity")) for item in items)
        if declared_total_qty > 0 and abs(sum_qty - declared_total_qty) / declared_total_qty > 0.05:
            warnings.append(
                f"Quantity mismatch: items sum to {sum_qty:.0f} but total_qty is {declared_total_qty:.0f}."
            )

        sum_amount = sum(_safe_float(item.get("amount")) for item in items)
        if declared_total_amount > 0 and abs(sum_amount - declared_total_amount) / declared_total_amount > 0.05:
            warnings.append(
                f"Amount mismatch: items sum to {sum_amount:.2f} but total_amount is {declared_total_amount:.2f}."
            )

    if _safe_float(totals.get("gross_weight")) == 0:
        warnings.append("Gross weight is zero or missing.")
    if _safe_int(totals.get("cartons")) == 0:
        warnings.append("Carton count is zero or missing.")

    return warnings


def validate_packing_list(data: dict) -> list[str]:
    warnings: list[str] = []

    if not data.get("invoice_number"):
        warnings.append("Invoice number is missing.")

    if _safe_int(data.get("total_cartons")) == 0:
        warnings.append("Total carton count is zero or missing.")

    weights = data.get("weights", {})
    if _safe_float(weights.get("gross_weight")) == 0:
        warnings.append("Gross weight is zero or missing.")
    if _safe_float(weights.get("net_weight")) == 0:
        warnings.append("Net weight is zero or missing.")
    if _safe_float(weights.get("volume")) == 0:
        warnings.append("Volume (CBM) is zero or missing.")

    sizes = data.get("sizes", {})
    total_size_qty = sum(_safe_int(v) for v in sizes.values())
    if total_size_qty == 0:
        warnings.append("All size quantities are zero — size breakdown may not have been extracted.")

    return warnings

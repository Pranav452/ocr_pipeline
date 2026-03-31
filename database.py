import logging
import pyodbc
from config import DB_CONNECTION_STRING

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def get_connection() -> pyodbc.Connection:
    try:
        return pyodbc.connect(DB_CONNECTION_STRING)
    except Exception as exc:
        logger.error("Failed to connect to MSSQL: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def save_invoice(data: dict) -> None:
    """Insert invoice header, line items into MSSQL. Rolls back on any error."""

    def _f(v, default=0.0):
        try:
            return float(v or default)
        except (ValueError, TypeError):
            return float(default)

    def _i(v, default=0):
        try:
            return int(float(v or default))
        except (ValueError, TypeError):
            return int(default)

    totals = data.get("totals", {})
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO invoices
              (invoice_number, invoice_date, po_no, buyer, consignee,
               total_qty, total_amount, gross_weight, net_weight, cbm, cartons)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("invoice_number"),
                data.get("invoice_date") or None,
                data.get("po_no"),
                data.get("buyer"),
                data.get("consignee"),
                _f(totals.get("total_qty")),
                _f(totals.get("total_amount")),
                _f(totals.get("gross_weight")),
                _f(totals.get("net_weight")),
                _f(totals.get("cbm")),
                _i(totals.get("cartons")),
            ),
        )
        for item in data.get("items", []):
            cur.execute(
                """
                INSERT INTO invoice_items
                  (invoice_number, description, hs_code, quantity, unit_price, amount)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("invoice_number"),
                    item.get("description"),
                    item.get("hs_code"),
                    _f(item.get("quantity")),
                    _f(item.get("unit_price")),
                    _f(item.get("amount")),
                ),
            )
        conn.commit()
        logger.info("Saved invoice %s to DB.", data.get("invoice_number"))
    except Exception as exc:
        conn.rollback()
        logger.error("Failed to save invoice: %s", exc)
        raise
    finally:
        conn.close()


def save_packing_list(data: dict) -> None:
    """Insert packing list + size breakdown (with proportional weight/volume) into MSSQL."""

    def _f(v, default=0.0):
        try:
            return float(v or default)
        except (ValueError, TypeError):
            return float(default)

    def _i(v, default=0):
        try:
            return int(float(v or default))
        except (ValueError, TypeError):
            return int(default)

    weights = data.get("weights", {})
    total_net_weight = _f(weights.get("net_weight"))
    total_volume = _f(weights.get("volume"))

    sizes = data.get("sizes", {})
    # Only count sizes with qty > 0 for proportion calculation
    size_qtys = {k: _i(v) for k, v in sizes.items() if _i(v) > 0}
    total_size_qty = sum(size_qtys.values())

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO packing_list
              (invoice_number, total_cartons, dimensions, gross_weight, net_weight, volume)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("invoice_number"),
                _i(data.get("total_cartons")),
                data.get("dimensions"),
                _f(weights.get("gross_weight")),
                total_net_weight,
                total_volume,
            ),
        )
        packing_id = cur.fetchone()[0]

        for size, qty in size_qtys.items():
            proportion = qty / total_size_qty if total_size_qty > 0 else 0
            size_net_weight = round(total_net_weight * proportion, 4)
            size_volume = round(total_volume * proportion, 6)
            cur.execute(
                """
                INSERT INTO size_breakdown (packing_id, size, quantity, net_weight, volume)
                VALUES (?, ?, ?, ?, ?)
                """,
                (packing_id, size, qty, size_net_weight, size_volume),
            )

        conn.commit()
        logger.info(
            "Saved packing list (id=%s) for invoice %s.",
            packing_id,
            data.get("invoice_number"),
        )
    except Exception as exc:
        conn.rollback()
        logger.error("Failed to save packing list: %s", exc)
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read operations (for /api/records)
# ---------------------------------------------------------------------------

def get_all_invoices() -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT invoice_number, invoice_date, po_no, buyer, consignee, "
            "total_qty, total_amount, gross_weight, net_weight, cbm, cartons "
            "FROM invoices ORDER BY invoice_number"
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def get_all_packing_lists() -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT p.id, p.invoice_number, p.total_cartons, p.dimensions, "
            "p.gross_weight, p.net_weight, p.volume, "
            "s.size, s.quantity, s.net_weight AS size_net_weight, s.volume AS size_volume "
            "FROM packing_list p "
            "LEFT JOIN size_breakdown s ON s.packing_id = p.id "
            "ORDER BY p.id, s.size"
        )
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
        # Group sizes back into each packing record
        records: dict[int, dict] = {}
        for row in rows:
            r = dict(zip(cols, row))
            pid = r["id"]
            if pid not in records:
                records[pid] = {
                    "id": pid,
                    "invoice_number": r["invoice_number"],
                    "total_cartons": r["total_cartons"],
                    "dimensions": r["dimensions"],
                    "gross_weight": r["gross_weight"],
                    "net_weight": r["net_weight"],
                    "volume": r["volume"],
                    "sizes": {},
                }
            if r["size"]:
                records[pid]["sizes"][r["size"]] = {
                    "quantity": r["quantity"],
                    "net_weight": r["size_net_weight"],
                    "volume": r["size_volume"],
                }
        return list(records.values())
    finally:
        conn.close()

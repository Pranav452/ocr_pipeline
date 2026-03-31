import asyncio
import decimal
import datetime
import json
import logging
import os
import time
import uuid

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import API_KEY
from database import (
    get_all_invoices,
    get_all_packing_lists,
    save_invoice,
    save_packing_list,
)
from llm_extractor import classify_and_extract
from ocr_engine import extract_text_from_pdf
from validator import validate_invoice, validate_packing_list

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="OCR Pipeline API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
os.makedirs("uploads", exist_ok=True)

# In-memory task store  { task_id: [event_dict, ...] }
task_progress: dict[str, list[dict]] = {}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _push(task_id: str, step: int, status: str, message: str, **extra) -> None:
    task_progress[task_id].append(
        {"step": step, "status": status, "message": message, **extra}
    )


async def process_document(task_id: str, file_path: str) -> None:
    loop = asyncio.get_running_loop()
    try:
        # Step 1 — upload already done
        _push(task_id, 1, "completed", "Document uploaded successfully.")

        # Step 2 — Text extraction (pdfplumber)
        _push(task_id, 2, "processing", "Extracting text from PDF...")
        raw_text = await loop.run_in_executor(None, extract_text_from_pdf, file_path)
        with open(f"{file_path}.ocr.txt", "w", encoding="utf-8") as f:
            f.write(raw_text)
        _push(task_id, 2, "completed", f"Text extraction complete ({len(raw_text)} chars).")

        # Step 3 — LLM Classification + Extraction
        _push(task_id, 3, "processing", "Classifying and extracting via GPT-4o-mini...")
        doc_type, extracted_data = await classify_and_extract(raw_text)
        with open(f"{file_path}.extracted.json", "w", encoding="utf-8") as f:
            json.dump({"type": doc_type, "data": extracted_data}, f, indent=2)
        _push(
            task_id, 3, "completed",
            f"Classified as {doc_type.replace('_', ' ').upper()}. Extraction complete.",
        )

        # Step 4 — Validation
        _push(task_id, 4, "processing", "Validating extracted fields...")
        if doc_type == "invoice":
            warnings = validate_invoice(extracted_data)
        else:
            warnings = validate_packing_list(extracted_data)

        if warnings:
            warning_text = " | ".join(warnings)
            _push(
                task_id, 4, "warning",
                f"Validation passed with {len(warnings)} warning(s): {warning_text}",
                warnings=warnings,
            )
        else:
            _push(task_id, 4, "completed", "Validation passed — all checks OK.")

        # Step 5 — DB Insert
        _push(task_id, 5, "processing", f"Saving {doc_type.upper()} to MSSQL...")
        if doc_type == "invoice":
            await loop.run_in_executor(None, save_invoice, extracted_data)
        else:
            await loop.run_in_executor(None, save_packing_list, extracted_data)
        _push(task_id, 5, "completed", "Data saved to MSSQL successfully.")

        # Step 6 — Done — include the extracted JSON in the final event
        _push(
            task_id, 6, "completed",
            "Pipeline finished successfully!",
            doc_type=doc_type,
            extracted=extracted_data,
            warnings=warnings,
        )

    except Exception as exc:
        logger.exception("Pipeline error for task %s", task_id)
        _push(task_id, 99, "error", f"Pipeline failed: {exc}")


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_ui():
    return FileResponse("static/index.html")


@app.post("/api/upload")
async def upload_document(
    background_tasks: BackgroundTasks, file: UploadFile = File(...)
):
    task_id = str(uuid.uuid4())
    task_progress[task_id] = []
    file_path = os.path.join("uploads", f"{task_id}_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(await file.read())
    background_tasks.add_task(process_document, task_id, file_path)
    return {"task_id": task_id}


@app.get("/api/progress/{task_id}")
async def progress_stream(task_id: str):
    """Server-Sent Events stream for real-time pipeline progress."""

    async def generate():
        sent = 0
        while True:
            events = task_progress.get(task_id, [])
            while sent < len(events):
                yield f"data: {json.dumps(events[sent])}\n\n"
                sent += 1
            # Stop streaming once terminal event delivered
            if events and events[-1].get("step") in (6, 99):
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/records")
async def get_records():
    """Return all stored invoices and packing lists."""
    loop = asyncio.get_running_loop()
    invoices = await loop.run_in_executor(None, get_all_invoices)
    packing_lists = await loop.run_in_executor(None, get_all_packing_lists)

    def _serialize(obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        return str(obj)

    return {
        "invoices": json.loads(json.dumps(invoices, default=_serialize)),
        "packing_lists": json.loads(json.dumps(packing_lists, default=_serialize)),
    }


# ---------------------------------------------------------------------------
# External API  —  POST /api/v1/extract
# For use by the Angular / .NET application.
# Accepts invoice + packing_list PDFs, returns extracted data as JSON.
# Does NOT save to DB — the consuming app handles that after user confirmation.
# ---------------------------------------------------------------------------

async def _extract_one(file: UploadFile, expected_type: str, tmp_path: str) -> dict:
    """Save upload, extract text, call LLM, validate. Returns result dict."""
    with open(tmp_path, "wb") as f:
        f.write(await file.read())
    loop = asyncio.get_running_loop()
    raw_text = await loop.run_in_executor(None, extract_text_from_pdf, tmp_path)
    doc_type, data = await classify_and_extract(raw_text)
    if doc_type != expected_type:
        raise ValueError(
            f"Expected a {expected_type.replace('_', ' ')} but got '{doc_type}'. "
            "Please check which file was uploaded in which field."
        )
    if doc_type == "invoice":
        warnings = validate_invoice(data)
    else:
        warnings = validate_packing_list(data)
    return {"data": data, "warnings": warnings}


@app.post(
    "/api/v1/extract",
    summary="Extract invoice + packing list data (no DB save)",
    tags=["External API"],
)
async def extract_documents(
    invoice: UploadFile = File(..., description="Commercial Invoice PDF"),
    packing_list: UploadFile = File(..., description="Packing List PDF"),
    x_api_key: str = Header(default="", alias="X-API-Key"),
):
    """
    **External API for Angular / .NET integration.**

    Upload both documents; receive structured JSON back.
    The calling application displays the data for user review before saving.

    - **invoice** — Commercial Invoice PDF
    - **packing_list** — Packing List PDF
    - **X-API-Key** header — required (set in .env → API_KEY)

    Returns extracted fields, per-size weight/volume breakdown, and any
    validation warnings. Nothing is written to the database.
    """
    # --- Auth ---
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")

    start = time.time()
    tmp_inv = os.path.join("uploads", f"ext_{uuid.uuid4()}_{invoice.filename}")
    tmp_pl  = os.path.join("uploads", f"ext_{uuid.uuid4()}_{packing_list.filename}")

    try:
        # Process both files in parallel
        inv_result, pl_result = await asyncio.gather(
            _extract_one(invoice,       "invoice",      tmp_inv),
            _extract_one(packing_list,  "packing_list", tmp_pl),
            return_exceptions=True,
        )

        # Build response — handle per-file errors gracefully
        def _result_block(result, label: str) -> dict:
            if isinstance(result, Exception):
                return {"status": "error", "error": str(result), "data": None, "warnings": []}
            return {"status": "ok", "data": result["data"], "warnings": result["warnings"]}

        inv_block = _result_block(inv_result, "invoice")
        pl_block  = _result_block(pl_result,  "packing_list")

        # Compute per-size net_weight + volume in the response payload
        # (same proportional formula used in database.py — so the caller sees it too)
        if pl_block["status"] == "ok" and pl_block["data"]:
            pl_data = pl_block["data"]
            weights = pl_data.get("weights", {})
            sizes   = pl_data.get("sizes", {})
            try:
                total_nw  = float(weights.get("net_weight") or 0)
                total_vol = float(weights.get("volume") or 0)
                total_qty = sum(int(v) for v in sizes.values() if int(v) > 0)
                size_breakdown = {}
                for size, qty in sizes.items():
                    qty = int(qty)
                    if qty > 0:
                        prop = qty / total_qty if total_qty else 0
                        size_breakdown[size] = {
                            "quantity":   qty,
                            "net_weight": round(total_nw * prop, 4),
                            "volume":     round(total_vol * prop, 6),
                        }
                pl_block["size_breakdown"] = size_breakdown
            except Exception:
                pl_block["size_breakdown"] = {}

        overall_status = (
            "success" if inv_block["status"] == "ok" and pl_block["status"] == "ok"
            else "partial_error"
        )

        return JSONResponse({
            "status": overall_status,
            "processing_time_ms": round((time.time() - start) * 1000),
            "invoice":      inv_block,
            "packing_list": pl_block,
        })

    finally:
        for p in (tmp_inv, tmp_pl):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

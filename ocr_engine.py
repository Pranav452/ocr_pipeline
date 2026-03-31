"""
OCR engine — pdfplumber only.
All client documents (HAPPYCHIC / JULES) are digitally generated PDFs;
pdfplumber extracts embedded text and tables perfectly with zero GPU needed.
"""

import logging
import pdfplumber

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text and tables from a digital PDF using pdfplumber."""
    full_text = ""
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            full_text += f"\n--- Page {i + 1} ---\n"
            for table in page.extract_tables():
                for row in table:
                    cleaned = [
                        cell.replace("\n", " ").strip() if cell else "" for cell in row
                    ]
                    full_text += "\t".join(cleaned) + "\n"
                full_text += "\n"
            text = page.extract_text(x_tolerance=3, y_tolerance=3)
            if text:
                full_text += text + "\n"
    logger.info("pdfplumber extracted %d chars from %s", len(full_text), file_path)
    return full_text.strip()

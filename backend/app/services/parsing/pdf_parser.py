from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader

from app.services.parsing.base import ParsedDocument, ParsedSection, ParserError


class PdfParser:
    source_type = "pdf"

    def parse(self, filename: str, data: bytes) -> ParsedDocument:
        if not data:
            raise ParserError("Uploaded PDF is empty.")
        try:
            reader = PdfReader(io.BytesIO(data))
        except Exception as exc:
            raise ParserError(f"PDF could not be opened: {exc}") from exc

        sections: list[ParsedSection] = []
        texts: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            texts.append(text)
            sections.append(ParsedSection(text=text, order=index - 1, page_number=index, source_uri=filename))
        full_text = "\n\n".join(texts).strip()
        if not full_text:
            raise ParserError("PDF text extraction returned empty content. OCR is not supported in this version.")
        document = ParsedDocument(
            title=(Path(filename).stem or "PDF Document")[:255],
            source_type="pdf",
            source_uri=filename,
            text=full_text,
            sections=sections,
            metadata={"filename": filename, "page_count": len(reader.pages)},
        )
        document.validate()
        return document

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from app.services.parsing.base import ParsedDocument, ParsedSection, ParserError
from app.services.parsing.text_parser import TextParser


class UrlParser:
    source_type = "url"

    def parse_html(self, url: str, html: str, title: str | None = None) -> ParsedDocument:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        page_title = title or (soup.title.string.strip() if soup.title and soup.title.string else url)
        text = soup.get_text("\n")
        parsed = TextParser().parse(title=page_title, text=text, source_uri=url)
        return ParsedDocument(
            title=parsed.title,
            source_type="url",
            source_uri=url,
            text=parsed.text,
            sections=[
                ParsedSection(
                    text=section.text,
                    order=section.order,
                    section_title=section.section_title,
                    source_uri=url,
                )
                for section in parsed.sections
            ],
            metadata={"url": url, "parser": "UrlParser"},
        )

    def fetch_snapshot(self, url: str) -> dict:
        try:
            response = httpx.get(url, timeout=20.0, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ParserError(f"URL fetch failed: {exc}") from exc
        return {"data": response.content, "content_type": response.headers.get("content-type", "text/html"),
                "encoding": response.encoding or "utf-8"}

    def fetch(self, url: str, title: str | None = None) -> ParsedDocument:
        # Compatibility helper; public imports persist fetch_snapshot before parsing.
        snapshot = self.fetch_snapshot(url)
        return self.parse_html(url, snapshot["data"].decode(snapshot["encoding"], errors="replace"), title)

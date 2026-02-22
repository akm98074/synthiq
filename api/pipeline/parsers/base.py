from dataclasses import dataclass


@dataclass
class PageText:
    """A single page's worth of extracted text."""
    page_number: int
    text: str

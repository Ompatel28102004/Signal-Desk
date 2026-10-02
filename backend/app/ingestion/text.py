import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_elements = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style"}:
            self._ignored_elements += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._ignored_elements:
            self._ignored_elements -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_elements:
            self.parts.append(data)


def html_to_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _TextExtractor()
    parser.feed(value)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text or None
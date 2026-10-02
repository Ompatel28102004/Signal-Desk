from abc import ABC, abstractmethod

from backend.app.ingestion.models import RawMention


class BaseSource(ABC):
    @property
    def enabled(self) -> bool:
        return True

    @property
    def disabled_message(self) -> str:
        return f"{self.source_name} source disabled"

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return this adapter's stable source identifier."""

    @abstractmethod
    def search(self, keyword: str, limit: int) -> list[RawMention]:
        """Search one source and map its response into RawMention values."""
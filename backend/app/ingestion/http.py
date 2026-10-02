import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from backend.app.ingestion.base import BaseSource


class SourceRequestError(RuntimeError):
    pass


class MalformedSourceResponse(ValueError):
    pass


class HttpSource(BaseSource):
    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.25,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._client = client
        self._sleep = sleep

    @contextmanager
    def _client_scope(self) -> Iterator[httpx.Client]:
        if self._client is not None:
            yield self._client
        else:
            with httpx.Client() as client:
                yield client

    def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        allow_error_status: bool = False,
    ) -> httpx.Response:
        return self._request(
            "GET",
            url,
            params=params,
            headers=headers,
            allow_error_status=allow_error_status,
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
        allow_error_status: bool = False,
    ) -> httpx.Response:
        with self._client_scope() as client:
            for attempt in range(self.max_retries + 1):
                delay = self.backoff_seconds * (2**attempt)
                try:
                    response = client.request(
                        method,
                        url,
                        params=params,
                        data=data,
                        headers=headers,
                        auth=auth,
                        timeout=self.timeout_seconds,
                    )
                except httpx.RequestError as error:
                    if attempt == self.max_retries:
                        raise SourceRequestError("source request exhausted retries") from error
                else:
                    if allow_error_status and response.status_code == 429:
                        return response
                    retryable_status = response.status_code == 429 or response.status_code >= 500
                    if retryable_status and attempt < self.max_retries:
                        retry_after = response.headers.get("Retry-After")
                        if retry_after is not None:
                            try:
                                delay = max(delay, min(float(retry_after), 30.0))
                            except ValueError:
                                pass
                    else:
                        if allow_error_status and response.is_error:
                            return response
                        try:
                            response.raise_for_status()
                        except httpx.HTTPStatusError as error:
                            raise SourceRequestError("source returned an unsuccessful HTTP status") from error
                        return response

                self._sleep(delay)

        raise SourceRequestError("source request failed")
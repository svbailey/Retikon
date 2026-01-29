from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

DEFAULT_INGEST_URL = "http://localhost:8081"
DEFAULT_QUERY_URL = "http://localhost:8080"
DEFAULT_TIMEOUT_S = 30


def _env_timeout() -> int:
    raw = os.getenv("RETIKON_TIMEOUT_S")
    if raw:
        try:
            return int(raw)
        except ValueError:
            return DEFAULT_TIMEOUT_S
    return DEFAULT_TIMEOUT_S


def _env_api_key() -> str | None:
    return os.getenv("QUERY_API_KEY") or os.getenv("INGEST_API_KEY")


@dataclass(frozen=True)
class RetikonClient:
    ingest_url: str | None = None
    query_url: str | None = None
    api_key: str | None = None
    timeout: int | None = None

    def __post_init__(self) -> None:
        ingest_url = (
            self.ingest_url
            or os.getenv("RETIKON_INGEST_URL")
            or DEFAULT_INGEST_URL
        )
        query_url = (
            self.query_url
            or os.getenv("RETIKON_QUERY_URL")
            or DEFAULT_QUERY_URL
        )
        api_key = self.api_key or _env_api_key()
        timeout = self.timeout if self.timeout is not None else _env_timeout()
        object.__setattr__(self, "ingest_url", ingest_url)
        object.__setattr__(self, "query_url", query_url)
        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "timeout", timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc

    def ingest(self, *, path: str, content_type: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"path": path}
        if content_type:
            payload["content_type"] = content_type
        return self._request("POST", f"{self.ingest_url.rstrip('/')}/ingest", payload)

    def query(
        self,
        *,
        query_text: str | None = None,
        image_base64: str | None = None,
        top_k: int = 5,
        mode: str | None = None,
        modalities: Iterable[str] | None = None,
        search_type: str | None = None,
        metadata_filters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"top_k": top_k}
        if query_text:
            payload["query_text"] = query_text
        if image_base64:
            payload["image_base64"] = image_base64
        if mode:
            payload["mode"] = mode
        if modalities is not None:
            payload["modalities"] = list(modalities)
        if search_type:
            payload["search_type"] = search_type
        if metadata_filters:
            payload["metadata_filters"] = metadata_filters
        return self._request("POST", f"{self.query_url.rstrip('/')}/query", payload)

    def health(self) -> dict[str, Any]:
        return self._request("GET", f"{self.query_url.rstrip('/')}/health")

    def reload_snapshot(self) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.query_url.rstrip('/')}/admin/reload-snapshot",
        )

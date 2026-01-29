from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class RetikonClient:
    ingest_url: str = "http://localhost:8081"
    query_url: str = "http://localhost:8080"
    api_key: str | None = None
    timeout: int = 30

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

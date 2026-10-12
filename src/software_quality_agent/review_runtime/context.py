"""context definitions for the SDK review workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from ..execution_errors import dependency_failure
from .checkpoint import CheckpointStore

# These are product-level safety caps for the bounded supplemental investigator.
# Formal TLR traversal is performed directly by Review Analysis and does not use
# the nested investigator budget.
MAX_SUPPLEMENTAL_PASSAGES = 5
MAX_EVIDENCE_INVESTIGATOR_TURNS = 5


@dataclass
class SuggestionContext:
    client: BackendClient
    store: CheckpointStore
    project_id: str
    review_id: str
    sentence_id: str
    tenant_id: str
    bound_run_id: str = ""
    bound_source_node_id: str = ""
    bound_target_artifact_ids: tuple[str, ...] = ()
    bound_target_node_ids: tuple[str, ...] = ()
    max_suggestion_revisions: int = 2
    # Runtime-only model admission settings.  They are not persisted as
    # credentials; the public checkpoint stores only the observed state.
    model_name: str = ""
    model_base_url: str | None = None
    model_api_key: str = ""
    model_context_window: int = 16_384
    model_safety_tokens: int = 512
    model_health_timeout_seconds: float = 4.0
    model_failure_limit: int = 2
    supplemental_passage_limit: int = MAX_SUPPLEMENTAL_PASSAGES
    passage_max_turns: int = MAX_EVIDENCE_INVESTIGATOR_TURNS
    review_pipeline: Literal["fixed_tlr", "full_investigation"] = "full_investigation"

    def __post_init__(self) -> None:
        self.max_suggestion_revisions = max(1, min(2, int(self.max_suggestion_revisions)))
        if self.review_pipeline not in {"fixed_tlr", "full_investigation"}:
            raise ValueError("unknown review pipeline")
        # Configuration may still contain the old larger values.  Clamp at the
        # runtime boundary so an environment override cannot silently restore
        # the unbounded supplemental-investigation behavior.
        self.supplemental_passage_limit = max(
            0, min(int(self.supplemental_passage_limit), MAX_SUPPLEMENTAL_PASSAGES)
        )
        if self.review_pipeline == "fixed_tlr":
            self.supplemental_passage_limit = 0
        self.passage_max_turns = max(
            1, min(int(self.passage_max_turns), MAX_EVIDENCE_INVESTIGATOR_TURNS)
        )


class BackendHTTPError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(f"backend HTTP {status_code}: {detail[:1000]}")


class BackendOwnershipError(BackendHTTPError):
    """A revoked worker must stop, not write a local semantic failure."""


class BackendClient:
    def __init__(self, base_url: str, tenant_id: str):
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.http = httpx.AsyncClient(timeout=60.0)
        self.execution_headers: dict[str, str] = {}

    async def close(self) -> None:
        await self.http.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = {"tenant_id": self.tenant_id, **(params or {})}
        try:
            response = await self.http.get(f"{self.base_url}{path}", params=query)
            if response.status_code in {401, 403, 429, 502, 503, 504}:
                response.raise_for_status()
        except httpx.HTTPError as exc:
            failure = dependency_failure(exc, "backend")
            if failure:
                raise failure from exc
            raise
        if response.status_code >= 400:
            raise BackendHTTPError(response.status_code, response.text)
        return response.json()

    async def write(
        self, method: str, path: str, payload: dict[str, Any], params: dict[str, Any] | None = None
    ) -> Any:
        query = {"tenant_id": self.tenant_id, **(params or {})}
        try:
            response = await self.http.request(
                method,
                f"{self.base_url}{path}",
                params=query,
                json=payload,
                headers=self.execution_headers,
            )
            if response.status_code in {401, 403, 429, 502, 503, 504}:
                response.raise_for_status()
        except httpx.HTTPError as exc:
            failure = dependency_failure(exc, "backend")
            if failure:
                raise failure from exc
            raise
        if response.status_code >= 400:
            if response.status_code == 409:
                raise BackendOwnershipError(response.status_code, response.text)
            raise BackendHTTPError(response.status_code, response.text)
        return response.json()

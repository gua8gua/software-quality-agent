"""Review suggestion service entry points; definitions live in the role/tool packages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .review_runtime.context import BackendClient
from .review_runtime.contracts import SuggestionOutput, SuggestionRequest


async def run_one_suggestion(
    *, settings: Any, request: SuggestionRequest, sentence_id: str, client: BackendClient
) -> SuggestionOutput:
    """Delegate to the single formal SDK workflow."""
    from .suggestion_workflow import run_one_suggestion as run_sdk_workflow

    return await run_sdk_workflow(
        settings=settings, request=request, sentence_id=sentence_id, client=client
    )


async def run_review_suggestions(*, settings: Any, request: SuggestionRequest) -> dict[str, Any]:
    """Iterate problematic review sentences; each sentence gets an independent SDK session."""
    client = BackendClient(settings.quality_backend_url, request.tenant_id)
    if request.worker_token and request.execution_attempt_id:
        client.execution_headers = {
            "X-Review-Worker": request.worker_token,
            "X-Review-Attempt": request.execution_attempt_id,
        }
    try:
        workspace = await client.get(
            f"/api/v1/projects/{request.project_id}/reviews/{request.review_id}/workspace"
        )
        if workspace.get("status") == "open":
            await client.write(
                "POST",
                f"/api/v1/projects/{request.project_id}/reviews/{request.review_id}/prepare",
                {},
            )
            workspace = await client.get(
                f"/api/v1/projects/{request.project_id}/reviews/{request.review_id}/workspace"
            )
        checks_by_sentence: dict[str, list[dict[str, Any]]] = {}
        if request.execution_attempt_id:
            await client.write(
                "POST",
                f"/api/v1/projects/{request.project_id}/reviews/{request.review_id}/resume-passages",
                {},
            )
            workspace = await client.get(
                f"/api/v1/projects/{request.project_id}/reviews/{request.review_id}/workspace"
            )
        for check in workspace.get("checks", []):
            checks_by_sentence.setdefault(check.get("sentence_id", ""), []).append(check)
        requested = set(request.sentence_ids or [])
        problem_ids = []
        for sentence in workspace.get("sentences", []):
            sentence_id = sentence.get("sentence_id")
            checks = checks_by_sentence.get(sentence_id, [])
            problematic = (
                not sentence.get("checks_finalized")
                or sentence.get("status") != "completed"
                or not (sentence.get("assessment") or {}).get("finalized")
                or (sentence.get("assessment") or {}).get("suggestion_required")
                or not checks
                or any(
                    item.get("status") in {"contradicted", "insufficient", "uncertain", "pending"}
                    for item in checks
                )
            )
            if sentence_id and (not requested or sentence_id in requested) and problematic:
                problem_ids.append(sentence_id)
        results = []
        for sentence_id in problem_ids:
            result = await run_one_suggestion(
                settings=settings, request=request, sentence_id=sentence_id, client=client)
            # Execution retry, not another reasoning workflow. SDK Session and
            # durable workspace remain authoritative; the second Runner sees
            # the actual previous error and skips exhausted local passage work.
            if (result.execution_status == "blocked"
                    and result.error_code not in {"model_retry_limit_exceeded", "incomplete_after_passage_failures", "no_fixed_tlr_material", "review_pipeline_changed"}
                    and int(getattr(settings, "review_model_retry_limit", 1)) > 0):
                result = await run_one_suggestion(
                    settings=settings, request=request, sentence_id=sentence_id, client=client)
            results.append(result.model_dump(mode="json"))
        status = (
            "completed"
            if results
            and all(item["execution_status"] in {"completed", "unresolved"} for item in results)
            else ("idle" if not results else "partial")
        )
        failures = [
            {key: item.get(key) for key in ("sentence_id", "error_code", "error_message")}
            for item in results
            if item["execution_status"] == "blocked"
        ]
        return {
            "review_id": request.review_id,
            "status": status,
            "error_code": "sentence_execution_failed" if failures else None,
            "error_message": "; ".join(
                f"{f['sentence_id']}: {f['error_code']}: {f['error_message']}" for f in failures
            )[:2000]
            or None,
            "sentence_errors": failures,
            "problem_sentence_count": len(problem_ids),
            "results": results,
        }
    finally:
        await client.close()


def read_suggestion_checkpoint(
    *, settings: Any, review_id: str, sentence_id: str
) -> dict[str, Any]:
    """Read the public checkpoint for one sentence without opening an Agent run."""
    root = Path(settings.suggestion_checkpoint_dir).resolve()
    path = (root / review_id / f"{sentence_id}.json").resolve()
    if not path.is_relative_to(root):
        raise ValueError("checkpoint path is outside configured checkpoint directory")
    if not path.exists():
        raise FileNotFoundError("suggestion checkpoint not found")
    return json.loads(path.read_text(encoding="utf-8"))

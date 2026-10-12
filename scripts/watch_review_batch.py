"""Observe an existing review batch; record changes only, never retry model work.

This read-only watcher is independent of the worker and survives an IDE turn.
It makes no TLR/embedding/model calls and does not synthesize or repair results.
"""
import argparse
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx


def watch_error_events(args):
    """Quiet background observer: snapshots only on terminal errors/end.

    The worker already owns deadlines and cancellation. This observer NEVER
    changes task state or retries anything. Persist deduplication across an
    observer restart and leave the public model transcripts in separate JSON.
    """
    output = args.evidence_dir or (Path(__file__).resolve().parents[1] / "artifacts/batch-monitor" / args.batch)
    output.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    state_file = output / "observer-state.json"
    seen = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    path = f"/api/v1/projects/{args.project}/reviews/batch/{args.batch}"

    def record(kind, key, data):
        signature = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        marker = f"{kind}:{key}"
        if seen.get(marker) == signature:
            return False
        event = {"at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
                 "kind": kind, "id": key, "data": data}
        with (output / "error-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(f"\n### {event['at']} · {kind} · {key}\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n")
        seen[marker] = signature
        temporary = state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(seen), encoding="utf-8")
        temporary.replace(state_file)
        print(json.dumps(event, ensure_ascii=False), flush=True)
        return True

    def save_json(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    with httpx.Client(base_url=args.url.rstrip("/"), timeout=30) as client:
        def read(endpoint, params=None):
            response = client.get(endpoint, params={"tenant_id": args.tenant, **(params or {})})
            response.raise_for_status()
            return response.json()

        record("observer_started", args.batch, {"project_id": args.project, "batch_id": args.batch,
               "read_only": True, "normal_progress_output": False, "interval_seconds": args.interval})
        while True:
            try:
                batch = read(path)
                for review in batch["reviews"]:
                    result = review.get("execution") or {}
                    if not (result.get("error_code") or result.get("error_message") or result.get("status") == "blocked"):
                        continue
                    marker = f"review_execution_error:{review['review_id']}"
                    signature = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    if seen.get(marker) == signature:
                        continue
                    # Capture once AFTER a real execution error. No healthy
                    # running workspace or growing model history is polled.
                    workspace = read(f"/api/v1/projects/{args.project}/reviews/{review['review_id']}/workspace")
                    save_json(f"{review['review_id']}-workspace.json", workspace)
                    for sentence in workspace.get("sentences", []):
                        response = client.get(f"/api/agent/review-suggestions/{review['review_id']}/{sentence['sentence_id']}",
                                              params={"tenant_id": args.tenant, "project_id": args.project})
                        if response.status_code == 404:
                            continue
                        response.raise_for_status()
                        save_json(f"{review['review_id']}-{sentence['sentence_id']}-checkpoint.json", response.json())
                    record("review_execution_error", review["review_id"], result)
                deadline = batch.get("lease_expires_at")
                if batch["status"] == "running" and deadline:
                    expiration = datetime.fromisoformat(deadline)
                    if expiration < datetime.now(timezone.utc):
                        record("worker_lease_expired", args.batch, {"lease_expires_at": deadline,
                               "note": "Execution heartbeat expired; native queue owns fencing/recovery. Observer did not restart anything."})
                if batch["status"] in {"completed", "partial", "interrupted", "blocked"}:
                    save_json("final-batch.json", batch)
                    record("batch_execution_ended", args.batch, {key: batch[key] for key in
                           ("status", "finished_count", "status_counts", "assessment_counts")})
                    record("observer_stopped", args.batch, {"reason": batch["status"],
                           "note": "No automatic retry or semantic fallback was executed"})
                    return
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                record("infrastructure_error", args.batch, {"error_code": type(exc).__name__, "message": str(exc)})
            time.sleep(args.interval)


def should_read_workspace(review, saved_marker):
    """A previous failed result must not hide a resumed live checkpoint."""
    result = review.get("execution")
    if not result:
        return review["status"] != "open"
    if result.get("status") not in {"completed", "idle"}:
        return True
    return saved_marker != json.dumps(result, sort_keys=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--url", default="http://10.71.29.93:18003")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--tenant", default="local")
    parser.add_argument("--errors-only", action="store_true")
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("interval must be positive")
    if args.errors_only:
        watch_error_events(args)
        return
    args.log.parent.mkdir(parents=True, exist_ok=True)
    output = Path(__file__).resolve().parents[1] / "artifacts/batch-monitor" / args.batch
    output.mkdir(parents=True, exist_ok=True)
    seen = {}
    path = f"/api/v1/projects/{args.project}/reviews/batch/{args.batch}"

    def record(kind, key, data):
        signature = json.dumps(data, ensure_ascii=False, sort_keys=True)
        if seen.get((kind, key)) == signature:
            return
        seen[kind, key] = signature
        at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        event = {"at": at, "kind": kind, "id": key, "data": data}
        with (output / "monitor-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(f"\n### {at} · {kind} · {key}\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n")
        print(json.dumps(event, ensure_ascii=False), flush=True)

    with httpx.Client(base_url=args.url, timeout=30) as client:
        def read(endpoint):
            response = client.get(endpoint, params={"tenant_id": "local"})
            response.raise_for_status()
            return response.json()

        while True:
            try:
                batch = read(path)
                (output / "latest-batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
                record("batch_progress", args.batch, {k: batch[k] for k in ("status", "finished_count", "status_counts")})
                for review in batch["reviews"]:
                    result = review.get("execution")
                    if result:
                        record("review_finished", review["review_id"], result)
                    if not should_read_workspace(review, seen.get(("workspace_saved", review["review_id"]))):
                        continue
                    workspace = read(f"/api/v1/projects/{args.project}/reviews/{review['review_id']}/workspace")
                    (output / f"{review['review_id']}-workspace.json").write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
                    for sentence in workspace["sentences"]:
                        response = client.get(f"/api/agent/review-suggestions/{review['review_id']}/{sentence['sentence_id']}",
                                              params={"project_id": args.project, "tenant_id": "local"})
                        if response.status_code == 404:
                            continue
                        response.raise_for_status()
                        checkpoint = response.json()
                        (output / f"{review['review_id']}-{sentence['sentence_id']}-checkpoint.json").write_text(
                            json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
                        errors = checkpoint.get("tool_errors", [])
                        record("sentence_state", sentence["sentence_id"], {
                            "review_id": review["review_id"], "stage": checkpoint.get("stage"),
                            "attempts": checkpoint.get("attempts"),
                            "last_started_at": checkpoint.get("last_started_at"),
                            "execution_status": checkpoint.get("workflow_status"),
                            "latest_error": errors[-1] if errors else None,
                            "error_count": len(errors), "result": checkpoint.get("latest_output")})
                    if result:
                        seen["workspace_saved", review["review_id"]] = json.dumps(result, sort_keys=True)
                # Maintenance/crashes may interrupt a batch which is explicitly
                # resumed later. Keep observing without restarting model work.
                if batch["status"] in {"completed", "partial"}:
                    record("watcher_stopped", args.batch, {"reason": batch["status"],
                           "note": "Execution completion is not semantic correctness; no automatic retry was performed"})
                    return
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                record("infrastructure_error", args.batch, {"error_code": type(exc).__name__, "message": str(exc)})
            time.sleep(args.interval)


if __name__ == "__main__":
    main()

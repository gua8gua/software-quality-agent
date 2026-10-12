"""Read-only snapshot of the existing batch and its public SDK checkpoints."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

BATCH = "aa62daed-8d58-47d6-aa6c-4c12ffbbfd93"
PROJECT = "real-srs-sds-20260929"
ROOT = "http://10.71.29.93:18003"
OUTPUT = Path(__file__).resolve().parents[1] / "artifacts/batch-monitor" / BATCH


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
    with httpx.Client(base_url=ROOT, timeout=30) as client:
        def read(path):
            response = client.get(path, params={"tenant_id": "local"})
            response.raise_for_status()
            return response.json()

        batch = read(f"/api/v1/projects/{PROJECT}/reviews/batch/{BATCH}")
        (OUTPUT / f"{timestamp}-batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = {key: batch[key] for key in ("batch_id", "status", "finished_count", "status_counts")}
        summary["observed_at"] = timestamp
        summary["reviews"] = []
        for review in batch["reviews"]:
            execution = review.get("execution")
            if not execution and review["status"] == "open":
                continue
            review_id = review["review_id"]
            workspace = read(f"/api/v1/projects/{PROJECT}/reviews/{review_id}/workspace")
            row = {"review_id": review_id, "node_id": review["requirement_node_id"], "execution": execution,
                   "preview": review["requirement_preview"], "workspace_status": workspace["status"],
                   "check_count": len(workspace["checks"]), "evidence_count": len(workspace["evidence"]),
                   "task_errors": [{k: task.get(k) for k in ("task_id", "role", "status", "error_code", "error_message")}
                                   for task in workspace["tasks"] if task["status"] in {"blocked", "failed"}],
                   "checkpoints": []}
            (OUTPUT / f"{review_id}-workspace.json").write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
            for sentence in workspace["sentences"]:
                response = client.get(f"/api/agent/review-suggestions/{review_id}/{sentence['sentence_id']}",
                                      params={"project_id": PROJECT, "tenant_id": "local"})
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                checkpoint = response.json()
                (OUTPUT / f"{review_id}-{sentence['sentence_id']}-checkpoint.json").write_text(
                    json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
                row["checkpoints"].append({"sentence_id": sentence["sentence_id"],
                    "latest_output": checkpoint.get("latest_output"),
                    "stage": checkpoint.get("stage"), "errors": checkpoint.get("errors", [])[-4:],
                    "tool_errors": checkpoint.get("tool_errors", [])[-6:],
                    "tool_count": len(checkpoint.get("tool_calls", [])),
                    "input_stats": checkpoint.get("model_input_stats", [])[-2:]})
            summary["reviews"].append(row)
    (OUTPUT / f"{timestamp}-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

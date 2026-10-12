"""Copy existing factual checkpoint failures into batch bookkeeping after repair.

Does not request LLM work, touch semantic statuses, invent evidence, or create a
new batch. --interrupted is explicit maintenance recovery for a stopped worker.
"""
import argparse
import json

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--project", required=True)
parser.add_argument("--batch", required=True)
parser.add_argument("--interrupted", action="store_true")
args = parser.parse_args()
root = "http://10.71.29.93:18003"
path = f"/api/v1/projects/{args.project}/reviews/batch/{args.batch}"
with httpx.Client(base_url=root, timeout=30) as client:
    def read(endpoint):
        response = client.get(endpoint, params={"tenant_id": "local"})
        response.raise_for_status()
        return response.json()

    batch = read(path)
    for review in batch["reviews"]:
        execution = review.get("execution") or {}
        if execution.get("status") in {"completed", "idle"} or execution.get("error_code"):
            continue
        if not execution and review["status"] == "open":
            continue
        workspace = read(f"/api/v1/projects/{args.project}/reviews/{review['review_id']}/workspace")
        results = []
        for sentence in workspace["sentences"]:
            response = client.get(f"/api/agent/review-suggestions/{review['review_id']}/{sentence['sentence_id']}",
                                  params={"project_id": args.project, "tenant_id": "local"})
            if response.status_code == 404:
                continue
            response.raise_for_status()
            checkpoint = response.json()
            output = checkpoint.get("latest_output")
            if output and output.get("execution_status") == "blocked":
                results.append(output)
            elif not output and args.interrupted:
                results.append({"sentence_id": sentence["sentence_id"], "execution_status": "blocked",
                                "error_code": "worker_interrupted",
                                "error_message": "Worker was stopped for generic error-handling repair before finishing this sentence"})
        if not results:
            continue
        result = {"status": "partial", "problem_sentence_count": len(workspace["sentences"]), "results": results}
        response = client.post(path + "/progress", params={"tenant_id": "local"},
                               json={"review_id": review["review_id"], "result": result})
        response.raise_for_status()
        print(json.dumps({"review_id": review["review_id"], "recovered_errors": results}, ensure_ascii=False), flush=True)
    if args.interrupted:
        response = client.post(path + "/interrupt", params={"tenant_id": "local"}, json={})
        response.raise_for_status()
        print(response.text)

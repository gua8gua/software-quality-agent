"""Explicitly resume failed workspace tasks via the existing official retry API.

Does not execute LLM/TLR, reset checks/passages/evidence, or clear failure events.
"""
import argparse
import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--project", required=True)
parser.add_argument("--batch", required=True)
args = parser.parse_args()
with httpx.Client(base_url="http://10.71.29.93:18003", timeout=30) as client:
    base = f"/api/v1/projects/{args.project}/reviews"
    params = {"tenant_id": "local"}
    response = client.get(base + "/batch/" + args.batch, params=params)
    response.raise_for_status()
    for review in response.json()["reviews"]:
        if review["status"] != "blocked":
            continue
        response = client.get(base + "/" + review["review_id"] + "/workspace", params=params)
        response.raise_for_status()
        tasks = [t for t in response.json()["tasks"] if t["task_key"] == "batch_execution"
                 and t["status"] in {"blocked", "failed"}]
        for task in tasks:
            response = client.post(base + f"/{review['review_id']}/tasks/{task['task_id']}/retry", params=params, json={})
            response.raise_for_status()
            print(review["review_id"], response.text, flush=True)

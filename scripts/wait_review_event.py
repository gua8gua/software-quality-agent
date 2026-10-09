"""Read-only, event-oriented observer for an existing server-side batch.

No model calls, retries, writes to the server, or intervention. Full public
checkpoints are downloaded only after a new failed sentence terminates.
"""
import argparse
import json
import os
import shlex
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import paramiko

ROOT = "/home/fuxin/software-quality-current/persistent-current/agent-state/checkpoints"
SCAN = """
import json, pathlib, sys
root, since, ids = pathlib.Path(sys.argv[1]), float(sys.argv[2]), set(json.loads(sys.argv[3]))
rows=[]
for folder in root.iterdir():
 if folder.name not in ids: continue
 for p in folder.glob('*.json'):
  if p.stat().st_mtime <= since: continue
  try: d=json.loads(p.read_text())
  except (OSError,ValueError): continue
  rows.append(dict(review_id=folder.name,sentence_id=p.stem,mtime=p.stat().st_mtime,
   started=d.get('last_started_at'),finished=d.get('last_finished_at'),attempt=d.get('attempts'),
   state=d.get('workflow_status'),result=d.get('latest_output')))
print(json.dumps(rows,ensure_ascii=False))
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--after", required=True, help="UTC ISO start of the resumed batch")
    parser.add_argument("--interval", type=float, default=60)
    args = parser.parse_args()
    after = datetime.fromisoformat(args.after).timestamp()
    output = Path(__file__).resolve().parents[1] / "artifacts/batch-monitor" / args.batch
    output.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(base_url="http://10.71.29.93:18003", timeout=30)
    path = f"/api/v1/projects/{args.project}/reviews/batch/{args.batch}"
    baseline = client.get(path).json()
    ids = [r["review_id"] for r in baseline["reviews"]]
    needed = {r["review_id"] for r in baseline["reviews"]
              if not ((r.get("execution") or {}).get("status") in {"completed", "idle"}
                      and (r.get("assessment") or {}).get("finalized"))}
    seen = set()
    cursor = after
    last_progress = time.monotonic()
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("10.71.29.93", username="fuxin", password=os.environ["INVENTORY_PASSWORD"], timeout=10)
    try:
        while True:
            command = "python3 -c " + shlex.quote(SCAN) + " " + shlex.quote(ROOT) + " " + str(cursor) + " " + shlex.quote(json.dumps(ids))
            _, stdout, stderr = ssh.exec_command(command, timeout=30)
            raw = stdout.read().decode("utf-8")
            if stdout.channel.recv_exit_status():
                raise RuntimeError(stderr.read().decode("utf-8"))
            rows = json.loads(raw)
            if rows:
                last_progress = time.monotonic()
                cursor = max(cursor, max(r["mtime"] for r in rows))
            for row in rows:
                if not row["finished"] or not row["started"] or row["finished"] < row["started"]:
                    continue
                marker = (row["sentence_id"], row["attempt"], row["finished"])
                if marker in seen:
                    continue
                seen.add(marker)
                needed.discard(row["review_id"])
                event = {"at": datetime.now(timezone.utc).isoformat(), **row}
                with (output / "event-observer.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                if (row.get("result") or {}).get("execution_status") == "blocked":
                    local = output / f"event-{row['review_id']}-{row['sentence_id']}-attempt{row['attempt']}.json"
                    with ssh.open_sftp() as sftp:
                        sftp.get(f"{ROOT}/{row['review_id']}/{row['sentence_id']}.json", str(local))
                    print(json.dumps({"event": "sentence_execution_error", "checkpoint": str(local), **row}, ensure_ascii=False), flush=True)
                    return
            if not needed:
                result = client.get(path).json()
                # A review may contain several sentences. Seeing one sentence
                # finish does not prove its review or the complete batch ended.
                if result["status"] in {"completed", "partial", "interrupted"}:
                    print(json.dumps({"event": "batch_execution_ended", "status": result["status"],
                                      "status_counts": result["status_counts"]}, ensure_ascii=False), flush=True)
                    return
            if time.monotonic() - last_progress >= 1800:
                print(json.dumps({"event": "no_checkpoint_activity_for_30_minutes", "remaining": len(needed)}), flush=True)
                return
            time.sleep(args.interval)
    finally:
        ssh.close()
        client.close()


if __name__ == "__main__":
    main()

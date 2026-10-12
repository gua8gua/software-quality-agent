"""Export public review workspaces for offline audit; never calls a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("review_ids", nargs="+")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30.0) as client:
        for review_id in args.review_ids:
            response = client.get(
                f"{args.base_url.rstrip('/')}/api/v1/projects/{args.project_id}"
                f"/reviews/{review_id}/workspace"
            )
            response.raise_for_status()
            workspace = response.json()
            if workspace.get("review_id") != review_id:
                raise ValueError("response review ID differs from requested ID")
            target = args.output_dir / f"{review_id}.workspace.json"
            target.write_text(json.dumps(workspace, ensure_ascii=False, indent=2),
                              encoding="utf-8")
            print(target)


if __name__ == "__main__":
    main()

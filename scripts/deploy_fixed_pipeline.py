"""Publish current sources through the server's established release mechanism.

No test suites, static checks, model calls or new analysis jobs are executed.
Credentials are process environment only. Existing data mounts are preserved.
"""

from __future__ import annotations

import json
import os
import shlex
import tarfile
from datetime import datetime
from pathlib import Path

import paramiko

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE_PROJECTS = PROJECT.parent
BACKEND = WORKSPACE_PROJECTS / "software-quality-management-backend"
REMOTE_ROOT = "/home/fuxin/software-quality-current/releases"
BASELINE = REMOTE_ROOT + "/20261008-031219"
NAMES = ["software-quality-current-api", "software-quality-current-workbench",
         "software-quality-current-review-worker", "software-quality-current-review-maintenance"]


def main():
    release = datetime.now().strftime("%Y%m%d-%H%M%S") + "-fixed-tlr"
    output = PROJECT / "artifacts" / "deployment" / release
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "sources.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        groups = [(BACKEND / "app", "backend/app"),
                  (BACKEND / "migrations", "backend/migrations"),
                  (PROJECT / "src", "agent/src"),
                  (PROJECT / "scripts", "agent/scripts"),
                  (PROJECT / "frontend/dist", "agent/frontend/dist")]
        for source, destination in groups:
            if not source.is_dir():
                raise RuntimeError(f"Missing deployment source: {source}")
            for file in sorted(source.rglob("*")):
                if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                    bundle.add(file, arcname=destination + "/" + file.relative_to(source).as_posix())
        for prefix, root, filenames in [
            ("backend", BACKEND, ["pyproject.toml", "README.md", "alembic.ini"]),
            ("agent", PROJECT, ["pyproject.toml", "README.md"]),
        ]:
            for filename in filenames:
                bundle.add(root / filename, arcname=prefix + "/" + filename)

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("10.71.29.93", username="fuxin", password=os.environ["QUALITY_DEPLOY_PASSWORD"], timeout=20)

    def command(command_text):
        _, stdout, stderr = client.exec_command(command_text, timeout=None)
        # Stream long Docker builds instead of filling the SSH channel buffer.
        stdout.channel.set_combine_stderr(True)
        for line in stdout:
            print(line, end="", flush=True)
        if stdout.channel.recv_exit_status() != 0:
            raise RuntimeError("Remote deployment command failed; see preceding output")

    try:
        _, stdout, _ = client.exec_command("docker inspect " + " ".join(NAMES), timeout=30)
        containers = json.loads(stdout.read())
        by_name = {row["Name"].lstrip("/"): row for row in containers}
        api_image = by_name[NAMES[0]]["Config"]["Image"]
        web_image = by_name[NAMES[1]]["Config"]["Image"]
        if not api_image.startswith("software-quality-api:") or not web_image.startswith("software-quality-workbench:"):
            raise RuntimeError("Unexpected live project images")
        remote = REMOTE_ROOT + "/" + release
        command("mkdir -m 700 " + shlex.quote(remote))
        with client.open_sftp() as sftp:
            with sftp.open(BASELINE + "/deploy_remote.py") as source:
                helper = source.read().decode("utf-8")
            old_filter = 'if not item.startswith(("CONSOLE_STATE_DB=", "REVIEW_QUEUE_DSN="))]'
            new_filter = 'if not item.startswith(("CONSOLE_STATE_DB=", "REVIEW_QUEUE_DSN=", "REVIEW_PIPELINE=", "REVIEW_MODEL_RETRY_LIMIT="))]'
            old_env = '"REVIEW_QUEUE_DSN=" + queue_dsn])'
            new_env = '"REVIEW_QUEUE_DSN=" + queue_dsn, "REVIEW_PIPELINE=fixed_tlr", "REVIEW_MODEL_RETRY_LIMIT=1"])'
            for old, new in [(old_filter, new_filter), (old_env, new_env)]:
                if helper.count(old) != 1:
                    raise RuntimeError("Deployment helper differs from the reviewed baseline")
                helper = helper.replace(old, new)
            for filename, content in [("deploy_remote.py", helper)]:
                with sftp.open(remote + "/" + filename, "w") as target:
                    target.write(content.encode("utf-8"))
            for filename, image in [("Dockerfile.api", api_image), ("Dockerfile.web", web_image)]:
                with sftp.open(BASELINE + "/" + filename) as source:
                    content = source.read().decode("utf-8")
                content = "FROM " + image + "\n" + content.split("\n", 1)[1]
                with sftp.open(remote + "/" + filename, "w") as target:
                    target.write(content.encode("utf-8"))
            sftp.put(str(archive), remote + "/sources.tar.gz")
        command("tar -xzf " + shlex.quote(remote + "/sources.tar.gz") + " -C " + shlex.quote(remote))
        print("Uploaded release " + release, flush=True)
        command("python3 " + shlex.quote(remote + "/deploy_remote.py") + " build-no-static-checks")
        command("python3 " + shlex.quote(remote + "/deploy_remote.py") + " activate")
        _, stdout, _ = client.exec_command("docker inspect " + " ".join(NAMES), timeout=30)
        deployed = json.loads(stdout.read())
        receipt = {"release": release, "remote_release": remote, "url": "http://10.71.29.93:18003",
                   "review_pipeline": "fixed_tlr", "tests_executed": False, "analysis_started": False,
                   "services": []}
        for row in deployed:
            env = dict(item.split("=", 1) for item in row["Config"]["Env"])
            receipt["services"].append({"name": row["Name"], "image": row["Config"]["Image"],
                "status": row["State"]["Status"], "review_pipeline": env.get("REVIEW_PIPELINE")})
        print(json.dumps(receipt, ensure_ascii=True, indent=2), flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()

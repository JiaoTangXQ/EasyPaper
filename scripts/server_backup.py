#!/usr/bin/env python3
"""Consistent, offline backup/restore of PostgreSQL AND persistent PDF files.

Uses only stdlib + Docker Compose. A backup briefly stops the backend. The
result contains secrets: local directory is mode 700, files are mode 600.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.prod.yml")]


def compose(*args, **kwargs):
    return subprocess.run([*COMPOSE, *args], cwd=ROOT, check=True, **kwargs)


def digest(path):
    with path.open("rb") as source:
        result = hashlib.sha256()
        while chunk := source.read(1024 * 1024):
            result.update(chunk)
        return result.hexdigest()


def running():
    return bool(compose("ps", "--status", "running", "-q", "backend", capture_output=True, text=True).stdout.strip())


def backup(destination):
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination, 0o700)
    # Never include a half-written archive in retention/upload selection.
    stage = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=destination))
    was_running = running()
    try:
        if was_running:
            compose("stop", "backend")
        with (stage / "database.dump").open("wb") as output:
            compose("exec", "-T", "db", "pg_dump", "-U", "easypaper", "-d", "easypaper", "-Fc", stdout=output)
        with (stage / "files.tar.gz").open("wb") as output:
            compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "tar", "backend",
                    "-czf", "-", "-C", "/app", "tmp", "reader-library", stdout=output)
        shutil.copyfile(ROOT / ".env", stage / "server.env")
        shutil.copyfile(ROOT / "deploy/config.production.yaml", stage / "config.production.yaml")
        manifest = {p.name: digest(p) for p in stage.iterdir()}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for path in stage.iterdir():
            path.chmod(0o600)
        target = destination / datetime.now(timezone.utc).strftime("easypaper-%Y%m%dT%H%M%S%fZ")
        stage.rename(target)
        print(f"备份完成：{target}")
        return target
    finally:
        if was_running:
            compose("start", "backend")


def verify(source):
    expected = {"database.dump", "files.tar.gz", "server.env", "config.production.yaml"}
    manifest = json.loads((source / "manifest.json").read_text())
    if set(manifest) != expected or any(digest(source / name) != checksum for name, checksum in manifest.items()):
        raise ValueError("备份校验失败，未执行恢复")
    with tarfile.open(source / "files.tar.gz", "r:gz") as archive:
        for member in archive:
            parts = Path(member.name).parts
            if not parts or parts[0] not in {"tmp", "reader-library"} or ".." in parts or not (member.isfile() or member.isdir()):
                raise ValueError("备份包含不安全路径或文件类型")


def restore(source, safety_destination):
    verify(source)
    # Preserve current state before replacing anything.
    backup(safety_destination)
    was_running = running()
    if was_running:
        compose("stop", "backend")
    # Keep backend stopped on failure: serving mixed DB/files would corrupt data.
    with (source / "files.tar.gz").open("rb") as data:
        compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "tar", "backend", "-xzf", "-", "-C", "/app", stdin=data)
    with (source / "database.dump").open("rb") as data:
        compose("exec", "-T", "db", "pg_restore", "-U", "easypaper", "-d", "easypaper",
                "--clean", "--if-exists", "--no-owner", "--single-transaction", "--exit-on-error", stdin=data)
    if was_running:
        compose("start", "backend")
    print("数据恢复完成。当前服务器密钥和配置保持不变；备份中的配置只用于人工灾难恢复。")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("backup").add_argument("destination", type=Path)
    sub.add_parser("verify").add_argument("source", type=Path)
    restoring = sub.add_parser("restore")
    restoring.add_argument("source", type=Path)
    restoring.add_argument("--safety-backup-dir", required=True, type=Path)
    restoring.add_argument("--confirm-replace", required=True, action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    # Avoid overlapping scheduled backups/restores (Linux/macOS).
    import fcntl
    with (ROOT / ".backup.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "backup":
            backup(args.destination.resolve())
        elif args.action == "verify":
            verify(args.source.resolve())
            print("校验通过")
        else:
            restore(args.source.resolve(), args.safety_backup_dir.resolve())


if __name__ == "__main__":
    main()

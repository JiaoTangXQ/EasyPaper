"""Scheduled server backup; retain seven complete, verified snapshots."""

import fcntl
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import server_backup  # noqa: E402


def main():
    with (ROOT / ".backup.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        destination = Path("/var/backups/easypaper")
        latest = server_backup.backup(destination)
        server_backup.verify(latest)
        completed = sorted(
            path
            for path in destination.glob("easypaper-*")
            if path.is_dir()
            and not path.is_symlink()
            and (path / "manifest.json").is_file()
        )
        for old in completed[:-7]:
            server_backup.verify(old)
            shutil.rmtree(old)
        print("Verified daily backup; retaining 7 completed backups.")


if __name__ == "__main__":
    import os

    os.umask(0o077)
    main()

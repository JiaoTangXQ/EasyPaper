"""Restore a same-account, same-paper archive without overwriting newer annotations."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session

from ..models.reading import ReaderAnnotation, ReaderVersion
from .synced_reader import KINDS, dumps

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024


def restore_archive(service, document_id, user_id, stream):
    service.owned(document_id, user_id)
    original = next(v for v in service.versions(document_id) if v.kind == "original")
    folder = Path(original.path).parent
    versions, annotations, files = [], [], []
    try:
        with zipfile.ZipFile(stream) as archive:
            if sum(i.file_size for i in archive.infolist()) > 512 * 1024 * 1024 or len(archive.infolist()) > 2000:
                raise ValueError("备份解压后过大")
            bundle = json.loads(archive.read("annotations.json"))
            if bundle["document_id"] != document_id or bundle["user_id"] != user_id:
                raise ValueError("只能导入当前账户、当前论文的备份")
            if len(bundle["versions"]) > 500 or len(bundle["annotations"]) > 10000:
                raise ValueError("备份记录过多")
            for item in bundle["versions"]:
                digest, kind = item["fingerprint"], item["kind"]
                if (
                    kind not in KINDS
                    or not re.fullmatch(r"[a-f0-9]{64}", digest)
                    or item["id"] != f"{document_id}:{kind}:{digest}"
                ):
                    raise ValueError("文件版本无效")
                name = f"{kind}-{digest}"
                data = archive.read(name + ".pdf")
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError("PDF 校验失败")
                index = json.loads(archive.read(name + ".index.json"))
                mappings = json.loads(archive.read(name + ".mappings.json"))
                # Keep the frozen index (and its IDs) across parser upgrades.
                if not index["pages"] or not isinstance(index["units"], list) or not isinstance(mappings, list):
                    raise ValueError("内容索引无效")
                for unit in index["units"]:
                    if (
                        not isinstance(unit["text"], str)
                        or not 0 <= unit["page"] < len(index["pages"])
                        or not isinstance(unit["chars"], list)
                    ):
                        raise ValueError("内容索引无效")
                version = ReaderVersion(
                    id=item["id"],
                    document_id=document_id,
                    kind=kind,
                    fingerprint=digest,
                    path=str(folder / (name + ".pdf")),
                    index_json=dumps(index),
                    mappings_json=dumps(mappings),
                    created_at=datetime.fromisoformat(item["created_at"]),
                )
                versions.append(version)
                files.append((Path(version.path), data))
            by_id = {v.id: v for v in versions}
            for item in bundle["annotations"]:
                if item["document_id"] != document_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", item["id"]):
                    raise ValueError("批注标识无效")
                version = by_id[item["source_version_id"]]
                service.validate_annotation(version, item["data"])
                if not isinstance(item["revision"], int) or item["revision"] < 1:
                    raise ValueError("批注修订无效")
                for vid, projections in item["projections"].items():
                    for p in projections:
                        service.validate_annotation(
                            by_id[vid],
                            {
                                "id": "projection",
                                "type": 9,
                                "pageIndex": p["page"],
                                "rect": p["rects"][0],
                                "segmentRects": p["rects"],
                            },
                        )
                annotations.append(
                    ReaderAnnotation(
                        id=item["id"],
                        document_id=document_id,
                        user_id=user_id,
                        source_version_id=version.id,
                        data_json=dumps(item["data"]),
                        quote=str(item["quote"])[:16000],
                        anchors_json=dumps(item["anchors"]),
                        projections_json=dumps(item["projections"]),
                        revision=item["revision"],
                        deleted=bool(item["deleted"]),
                        alignment_status=item["alignment_status"],
                        alignment_message=item["alignment_message"],
                        updated_at=datetime.fromisoformat(item["updated_at"]),
                    )
                )
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, IndexError, zipfile.BadZipFile, RuntimeError) as exc:
        raise HTTPException(422, "备份无效、内容不完整或不属于当前账户的这篇论文") from exc

    restored, skipped = 0, 0
    with Session(service.engine) as session:
        # Validate all identity collisions before publishing files or rows.
        for a in annotations:
            old = session.get(ReaderAnnotation, a.id)
            if old and (old.document_id != document_id or old.user_id != user_id):
                raise HTTPException(409, "批注标识冲突，未导入")
        for path, data in files:
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(data).hexdigest():
                temporary = folder / f".{uuid.uuid4().hex}.tmp"
                try:
                    temporary.write_bytes(data)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
        for v in versions:
            if not session.get(ReaderVersion, v.id):
                session.add(v)
        session.flush()
        for a in annotations:
            if session.get(ReaderAnnotation, a.id):
                skipped += 1
            else:
                session.add(a)
                restored += 1
        session.commit()
    return {"restored": restored, "skipped": skipped, "versions": len(versions)}

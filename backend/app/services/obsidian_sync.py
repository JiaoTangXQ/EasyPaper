"""Local Obsidian vault sync for EasyPaper knowledge notes."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..models.knowledge import (
    Flashcard,
    KnowledgeEntity,
    ObsidianSyncMapping,
    PaperKnowledge,
    UserAnnotation,
    UserSetting,
)
from ..models.task import Task
from .obsidian_markdown import (
    build_entity_markdown,
    build_paper_markdown,
    normalize_entity_key,
    sanitize_markdown_name,
)

OBSIDIAN_SETTING_KEY = "obsidian"

_LOCK_GUARD = threading.Lock()
_PAPER_LOCKS: dict[tuple[int, str], threading.Lock] = {}


@dataclass
class DetectedVault:
    name: str
    path: str
    exists: bool
    writable: bool
    open: bool = False


def get_obsidian_sync_lock(user_id: int, paper_id: str) -> threading.Lock:
    key = (user_id, paper_id)
    with _LOCK_GUARD:
        if key not in _PAPER_LOCKS:
            _PAPER_LOCKS[key] = threading.Lock()
        return _PAPER_LOCKS[key]


class ObsidianVaultDetector:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path

    def detect(self) -> list[DetectedVault]:
        config_path = self.config_path or self._default_config_path()
        if not config_path.exists():
            return []

        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        raw_vaults = payload.get("vaults", {})
        if isinstance(raw_vaults, dict):
            entries = raw_vaults.items()
        elif isinstance(raw_vaults, list):
            entries = [(str(index), item) for index, item in enumerate(raw_vaults)]
        else:
            return []

        vaults: list[DetectedVault] = []
        for vault_id, item in entries:
            if not isinstance(item, dict):
                continue
            raw_path = item.get("path")
            if not raw_path:
                continue
            path = Path(str(raw_path)).expanduser()
            name = str(item.get("name") or path.name or vault_id)
            exists = path.exists() and path.is_dir()
            vaults.append(
                DetectedVault(
                    name=name,
                    path=str(path),
                    exists=exists,
                    writable=exists and os.access(path, os.W_OK),
                    open=bool(item.get("open", False)),
                )
            )
        return vaults

    @staticmethod
    def _default_config_path() -> Path:
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
        if sys.platform.startswith("win"):
            appdata = os.environ.get("APPDATA")
            base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
            return base / "obsidian" / "obsidian.json"
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg_config) if xdg_config else Path.home() / ".config"
        return base / "obsidian" / "obsidian.json"


class ObsidianSyncService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def detect_vaults(self) -> list[dict[str, Any]]:
        return [asdict(vault) for vault in ObsidianVaultDetector().detect()]

    def get_settings(self, user_id: int) -> dict[str, Any] | None:
        setting = self.session.get(UserSetting, self._setting_id(user_id))
        if not setting:
            return None
        try:
            data = json.loads(setting.value_json)
        except json.JSONDecodeError:
            return None
        return {
            "vault_path": data.get("vault_path", ""),
            "root_folder": data.get("root_folder") or "EasyPaper",
            "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
        }

    def save_settings(self, *, user_id: int, vault_path: str, root_folder: str = "EasyPaper") -> dict[str, Any]:
        vault = Path(vault_path).expanduser()
        if not vault.exists() or not vault.is_dir():
            raise ValueError("Obsidian vault 路径不存在")
        if not os.access(vault, os.W_OK):
            raise ValueError("Obsidian vault 不可写")

        normalized_root = self._normalize_root_folder(root_folder)
        value = {"vault_path": str(vault), "root_folder": normalized_root}
        setting = self.session.get(UserSetting, self._setting_id(user_id))
        if not setting:
            setting = UserSetting(
                id=self._setting_id(user_id),
                user_id=user_id,
                key=OBSIDIAN_SETTING_KEY,
                value_json=json.dumps(value, ensure_ascii=False),
            )
        else:
            setting.value_json = json.dumps(value, ensure_ascii=False)
            setting.updated_at = datetime.utcnow()
        self.session.add(setting)
        self.session.commit()
        return self.get_settings(user_id) or value

    def test_write(self, *, vault_path: str, root_folder: str = "EasyPaper") -> dict[str, Any]:
        vault = Path(vault_path).expanduser()
        if not vault.exists() or not vault.is_dir():
            raise ValueError("Obsidian vault 路径不存在")
        root = vault / self._normalize_root_folder(root_folder)
        root.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".easypaper-test-", suffix=".tmp", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("ok")
                handle.flush()
                os.fsync(handle.fileno())
            Path(tmp_name).unlink(missing_ok=True)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return {"writable": True, "path": str(root)}

    def sync_paper(self, *, user_id: int, paper_id: str) -> dict[str, Any]:
        settings = self.get_settings(user_id)
        if not settings:
            raise ValueError("尚未配置 Obsidian vault")

        paper = self.session.get(PaperKnowledge, paper_id)
        if not paper or paper.user_id != user_id:
            raise LookupError("论文不存在")
        if not paper.knowledge_json:
            raise ValueError("论文知识尚未提取")

        vault_path = Path(settings["vault_path"]).expanduser()
        root_folder = self._normalize_root_folder(settings.get("root_folder") or "EasyPaper")
        if not vault_path.exists() or not vault_path.is_dir():
            raise ValueError("Obsidian vault 路径不存在")

        paper_data = self._paper_data(paper)
        title = self._paper_title(paper, paper_data)
        occupied: set[str] = set()
        errors: list[str] = []
        written = 0
        skipped = 0

        paper_relative = self._resolve_relative_path(
            user_id=user_id,
            paper_id=paper_id,
            item_type="paper",
            item_id=paper_id,
            normalized_key=paper_id,
            source_name=title,
            vault_path=vault_path,
            root_folder=root_folder,
            folder_name="Papers",
            desired_name=sanitize_markdown_name(title),
            frontmatter={"easypaper_type": "paper", "easypaper_id": paper_id},
            occupied=occupied,
        )
        paper_target = Path(paper_relative).stem
        note_link = sanitize_markdown_name(f"{paper_target} - Notes")

        entities = self._extract_entities(paper, paper_data)
        entity_paths: dict[str, str] = {}
        entity_items: list[dict[str, Any]] = []
        for entity in entities:
            entity_name = entity["name"]
            entity_key = normalize_entity_key(entity_name)
            relative = self._resolve_relative_path(
                user_id=user_id,
                paper_id=paper_id,
                item_type="entity",
                item_id=entity_key,
                normalized_key=entity_key,
                source_name=entity_name,
                vault_path=vault_path,
                root_folder=root_folder,
                folder_name="Entities",
                desired_name=sanitize_markdown_name(entity_name),
                frontmatter={"easypaper_type": "entity", "easypaper_entity_key": entity_key},
                occupied=occupied,
            )
            entity_paths[entity_key] = relative
            entity_items.append({**entity, "entity_key": entity_key, "relative_path": relative})

        entity_links = {key: Path(relative).stem for key, relative in entity_paths.items()}
        paper_content = build_paper_markdown(
            paper_id=paper_id,
            paper=paper_data,
            title=title,
            note_link=note_link,
            entity_links=entity_links,
        )
        try:
            state = self._write_and_update_mapping(
                user_id=user_id,
                paper_id=paper_id,
                item_type="paper",
                item_id=paper_id,
                normalized_key=paper_id,
                source_name=title,
                vault_path=vault_path,
                relative_path=paper_relative,
                content=paper_content,
            )
            if state == "skipped":
                skipped += 1
            else:
                written += 1
        except Exception as exc:
            errors.append(f"论文笔记写入失败：{exc}")

        for entity in entity_items:
            try:
                paper_links = self._paper_links_for_entity(
                    user_id=user_id,
                    current_paper_id=paper_id,
                    current_paper_title=title,
                    current_paper_target=paper_target,
                    entity_key=entity["entity_key"],
                )
                content = build_entity_markdown(
                    entity_key=entity["entity_key"],
                    entity_name=entity["name"],
                    entity_type=entity.get("type") or "concept",
                    definition=entity.get("definition") or "",
                    paper_links=paper_links,
                    relationships=self._relationships_for_entity(paper_data, entity["entity_key"]),
                    entity_links=entity_links,
                )
                state = self._write_and_update_mapping(
                    user_id=user_id,
                    paper_id=paper_id,
                    item_type="entity",
                    item_id=entity["entity_key"],
                    normalized_key=entity["entity_key"],
                    source_name=entity["name"],
                    vault_path=vault_path,
                    relative_path=entity["relative_path"],
                    content=content,
                )
                if state == "skipped":
                    skipped += 1
                else:
                    written += 1
            except Exception as exc:
                errors.append(f"实体笔记 {entity['name']} 写入失败：{exc}")

        status = "partial" if errors else "synced"
        return {
            "status": status,
            "paper_id": paper_id,
            "vault_path": str(vault_path),
            "root_folder": root_folder,
            "paper_note": paper_relative,
            "files_written": written,
            "files_skipped": skipped,
            "errors": errors,
        }

    @staticmethod
    def _setting_id(user_id: int) -> str:
        return f"user:{user_id}:obsidian"

    @staticmethod
    def _normalize_root_folder(root_folder: str) -> str:
        value = (root_folder or "EasyPaper").strip().strip("/\\")
        if not value:
            return "EasyPaper"
        parts = Path(value).parts
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("同步目录不能包含 . 或 ..")
        return value

    def _paper_data(self, paper: PaperKnowledge) -> dict[str, Any]:
        data = json.loads(paper.knowledge_json or "{}")
        if not isinstance(data, dict):
            data = {}
        data.setdefault("id", paper.id)
        metadata = data.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata.setdefault("title", paper.title)
        if paper.task_id:
            task = self.session.get(Task, paper.task_id)
            if task and task.summary_json:
                try:
                    summary_page = json.loads(task.summary_json)
                    if isinstance(summary_page, dict):
                        data["summary_page"] = summary_page
                except json.JSONDecodeError:
                    pass

        flashcards = self.session.exec(
            select(Flashcard).where(Flashcard.paper_id == paper.id).where(Flashcard.user_id == paper.user_id)
        ).all()
        if flashcards:
            data["flashcards"] = [
                {
                    "id": card.id,
                    "front": card.front,
                    "back": card.back,
                    "tags": self._json_list(card.tags_json),
                    "difficulty": card.difficulty,
                    "srs": {
                        "interval_days": card.interval_days,
                        "ease_factor": card.ease_factor,
                        "repetitions": card.repetitions,
                        "next_review": card.next_review.isoformat() if card.next_review else None,
                        "last_review": card.last_review.isoformat() if card.last_review else None,
                    },
                }
                for card in flashcards
            ]

        annotations = self.session.exec(
            select(UserAnnotation)
            .where(UserAnnotation.paper_id == paper.id)
            .where(UserAnnotation.user_id == paper.user_id)
            .order_by(UserAnnotation.created_at)
        ).all()
        data["annotations"] = [
            {
                "id": annotation.id,
                "type": annotation.type,
                "content": annotation.content,
                "target_type": annotation.target_type,
                "target_id": annotation.target_id,
                "tags": self._json_list(annotation.tags_json),
                "created_at": annotation.created_at.isoformat() if annotation.created_at else None,
            }
            for annotation in annotations
        ]
        return data

    @staticmethod
    def _json_list(value: str | None) -> list[Any]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def _paper_title(paper: PaperKnowledge, paper_data: dict[str, Any]) -> str:
        metadata = paper_data.get("metadata") if isinstance(paper_data.get("metadata"), dict) else {}
        title = metadata.get("title") or paper_data.get("title") or paper.title or "Untitled"
        return str(title).strip() or "Untitled"

    def _extract_entities(self, paper: PaperKnowledge, paper_data: dict[str, Any]) -> list[dict[str, str]]:
        raw_entities = paper_data.get("entities") if isinstance(paper_data.get("entities"), list) else []
        entities: list[dict[str, str]] = []
        for item in raw_entities:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            entities.append(
                {
                    "name": name,
                    "type": str(item.get("type") or item.get("entity_type") or "concept"),
                    "definition": str(item.get("definition") or item.get("description") or ""),
                }
            )

        if not entities:
            indexed = self.session.exec(select(KnowledgeEntity).where(KnowledgeEntity.paper_id == paper.id)).all()
            for item in indexed:
                entities.append(
                    {
                        "name": item.name,
                        "type": item.type,
                        "definition": item.definition or "",
                    }
                )

        deduped: dict[str, dict[str, str]] = {}
        for entity in entities:
            deduped.setdefault(normalize_entity_key(entity["name"]), entity)
        return list(deduped.values())

    def _resolve_relative_path(
        self,
        *,
        user_id: int,
        paper_id: str,
        item_type: str,
        item_id: str,
        normalized_key: str,
        source_name: str,
        vault_path: Path,
        root_folder: str,
        folder_name: str,
        desired_name: str,
        frontmatter: dict[str, str],
        occupied: set[str],
    ) -> str:
        mapping = self._get_mapping(
            user_id=user_id,
            paper_id=paper_id,
            item_type=item_type,
            item_id=item_id,
            vault_path=vault_path,
        )
        if mapping:
            mapped = self._target_from_relative(vault_path, mapping.relative_path)
            if mapped and mapped.exists():
                relative = self._relative_to_vault(vault_path, mapped)
                occupied.add(relative)
                return relative

        found = self._scan_frontmatter(vault_path, frontmatter)
        if found:
            relative = self._relative_to_vault(vault_path, found)
            occupied.add(relative)
            return relative

        base_relative = str(Path(root_folder) / folder_name / f"{desired_name}.md")
        base_relative = Path(base_relative).as_posix()
        if base_relative not in occupied and not (vault_path / base_relative).exists():
            occupied.add(base_relative)
            return base_relative

        suffix = hashlib.sha1(f"{item_type}:{normalized_key}:{source_name}".encode()).hexdigest()[:3]
        for index in range(50):
            suffix_part = suffix if index == 0 else f"{suffix}-{index + 1}"
            relative = str(Path(root_folder) / folder_name / f"{desired_name}-{suffix_part}.md")
            relative = Path(relative).as_posix()
            if relative not in occupied and not (vault_path / relative).exists():
                occupied.add(relative)
                return relative

        raise RuntimeError(f"无法为 {source_name} 生成不冲突的 Obsidian 文件名")

    def _write_and_update_mapping(
        self,
        *,
        user_id: int,
        paper_id: str,
        item_type: str,
        item_id: str,
        normalized_key: str,
        source_name: str,
        vault_path: Path,
        relative_path: str,
        content: str,
    ) -> str:
        target = vault_path / relative_path
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        mapping = self._get_mapping(
            user_id=user_id,
            paper_id=paper_id,
            item_type=item_type,
            item_id=item_id,
            vault_path=vault_path,
        )

        if mapping and mapping.content_hash == digest and target.exists():
            self._upsert_mapping(
                mapping=mapping,
                user_id=user_id,
                paper_id=paper_id,
                item_type=item_type,
                item_id=item_id,
                normalized_key=normalized_key,
                source_name=source_name,
                vault_path=vault_path,
                relative_path=relative_path,
                content_hash=digest,
            )
            return "skipped"

        self._atomic_write(target, content)
        self._upsert_mapping(
            mapping=mapping,
            user_id=user_id,
            paper_id=paper_id,
            item_type=item_type,
            item_id=item_id,
            normalized_key=normalized_key,
            source_name=source_name,
            vault_path=vault_path,
            relative_path=relative_path,
            content_hash=digest,
        )
        return "written"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{hashlib.sha1(os.urandom(16)).hexdigest()[:8]}.tmp")
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def _get_mapping(
        self,
        *,
        user_id: int,
        paper_id: str,
        item_type: str,
        item_id: str,
        vault_path: Path,
    ) -> ObsidianSyncMapping | None:
        return self.session.get(
            ObsidianSyncMapping,
            self._mapping_id(user_id, paper_id, item_type, item_id, str(vault_path)),
        )

    def _upsert_mapping(
        self,
        *,
        mapping: ObsidianSyncMapping | None,
        user_id: int,
        paper_id: str,
        item_type: str,
        item_id: str,
        normalized_key: str,
        source_name: str,
        vault_path: Path,
        relative_path: str,
        content_hash: str,
    ) -> None:
        if not mapping:
            mapping = ObsidianSyncMapping(
                id=self._mapping_id(user_id, paper_id, item_type, item_id, str(vault_path)),
                user_id=user_id,
                paper_id=paper_id,
                item_type=item_type,
                item_id=item_id,
                source_name=source_name,
                normalized_key=normalized_key,
                vault_path=str(vault_path),
                relative_path=relative_path,
                content_hash=content_hash,
            )
        else:
            mapping.source_name = source_name
            mapping.normalized_key = normalized_key
            mapping.vault_path = str(vault_path)
            mapping.relative_path = relative_path
            mapping.content_hash = content_hash
            mapping.updated_at = datetime.utcnow()
        self.session.add(mapping)
        self.session.commit()

    @staticmethod
    def _mapping_id(user_id: int, paper_id: str, item_type: str, item_id: str, vault_path: str) -> str:
        raw = f"{user_id}:{paper_id}:{item_type}:{item_id}:{vault_path}"
        return f"obs_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]}"

    @staticmethod
    def _target_from_relative(vault_path: Path, relative_path: str) -> Path | None:
        target = (vault_path / relative_path).resolve()
        try:
            target.relative_to(vault_path.resolve())
        except ValueError:
            return None
        return target

    @staticmethod
    def _relative_to_vault(vault_path: Path, path: Path) -> str:
        return path.resolve().relative_to(vault_path.resolve()).as_posix()

    @staticmethod
    def _scan_frontmatter(vault_path: Path, expected: dict[str, str]) -> Path | None:
        if not vault_path.exists():
            return None
        for path in vault_path.rglob("*.md"):
            if any(part.startswith(".") for part in path.relative_to(vault_path).parts):
                continue
            frontmatter = _read_frontmatter(path)
            if all(frontmatter.get(key) == value for key, value in expected.items()):
                return path
        return None

    def _paper_links_for_entity(
        self,
        *,
        user_id: int,
        current_paper_id: str,
        current_paper_title: str,
        current_paper_target: str,
        entity_key: str,
    ) -> list[tuple[str, str]]:
        paper_ids = {current_paper_id}
        entity_mappings = self.session.exec(
            select(ObsidianSyncMapping)
            .where(ObsidianSyncMapping.user_id == user_id)
            .where(ObsidianSyncMapping.item_type == "entity")
            .where(ObsidianSyncMapping.normalized_key == entity_key)
        ).all()
        paper_ids.update(mapping.paper_id for mapping in entity_mappings)

        indexed_entities = self.session.exec(select(KnowledgeEntity).where(KnowledgeEntity.user_id == user_id)).all()
        for entity in indexed_entities:
            if normalize_entity_key(entity.name) == entity_key:
                paper_ids.add(entity.paper_id)

        papers = self.session.exec(select(PaperKnowledge).where(PaperKnowledge.id.in_(paper_ids))).all()
        paper_by_id = {paper.id: paper for paper in papers}
        links: list[tuple[str, str]] = []
        for paper_id in sorted(paper_ids):
            if paper_id == current_paper_id:
                links.append((current_paper_title, current_paper_target))
                continue
            paper = paper_by_id.get(paper_id)
            if not paper:
                continue
            title = paper.title or paper_id
            paper_mapping = self.session.exec(
                select(ObsidianSyncMapping)
                .where(ObsidianSyncMapping.user_id == user_id)
                .where(ObsidianSyncMapping.paper_id == paper_id)
                .where(ObsidianSyncMapping.item_type == "paper")
            ).first()
            target = Path(paper_mapping.relative_path).stem if paper_mapping else sanitize_markdown_name(title)
            links.append((title, target))
        return links

    @staticmethod
    def _relationships_for_entity(paper_data: dict[str, Any], entity_key: str) -> list[dict[str, Any]]:
        relationships = paper_data.get("relationships")
        if not isinstance(relationships, list):
            return []
        related: list[dict[str, Any]] = []
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            source = str(relationship.get("source") or "")
            target = str(relationship.get("target") or "")
            if normalize_entity_key(source) == entity_key or normalize_entity_key(target) == entity_key:
                related.append(relationship)
        return related


def _read_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        data[key.strip()] = value
    return data

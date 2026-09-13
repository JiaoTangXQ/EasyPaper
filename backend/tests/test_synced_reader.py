from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import get_current_user
from app.api.reader_routes import create_reader_router
from app.core.config import LLMConfig
from app.models.reading import ReaderAnnotation, ReaderDocument, ReaderOperation, ReaderVersion
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.services.reader_geometry import char_rects, copied_projection, locate_quote, pdf_index, text_anchor, union
from app.services.reading_service import ReadingService

EN = "The method uses 30% less memory."
ZH = "该方法将内存占用降低30%。"
SIMPLE = "This method needs 30% less memory."


def pdf_bytes(text, chinese=False):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 80), text, fontname="china-s" if chinese else "helv", fontsize=12)
        return pdf.tobytes()


@pytest.fixture
def reader(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    source = tmp_path / "original.pdf"
    chinese = tmp_path / "chinese.pdf"
    dual = tmp_path / "dual.pdf"
    source.write_bytes(pdf_bytes(EN))
    chinese.write_bytes(pdf_bytes(ZH, True))
    with fitz.open(source) as en, fitz.open(chinese) as zh, fitz.open() as both:
        both.insert_pdf(en)
        both.insert_pdf(zh)
        dual.write_bytes(both.tobytes())
    config = SimpleNamespace(
        processing=SimpleNamespace(max_concurrent=1),
        llm=LLMConfig(api_key="test"),
        storage=SimpleNamespace(temp_dir=str(tmp_path / "library")),
    )
    reading = ReadingService(config, engine)

    async def align(_prompt, context):
        request = json.loads(context)
        # The model is stubbed. The API must still ground every proposed substring in the PDF.
        candidates = request["candidates"]
        support = request["selection"] if "selection" in request else request["source_context"][0]["sentence"]
        if request.get("phase") == "phrase_boundaries" and EN in support:
            support = "30% less memory"
        matches = [
            {
                "id": c["id"],
                "quote": c["text"],
                "confidence": 0.99,
                "source_index": 0,
                "source_quote": support,
            }
            for c in candidates
            if "30%" in c["text"]
        ]
        return {"matches": matches}

    reading.ask_model = align
    user = User(id=1, email="one@example.com", hashed_password="unused")
    with Session(engine) as session:
        session.add(user)
        session.add(User(id=2, email="two@example.com", hashed_password="unused"))
        session.add(
            Task(
                task_id="paper",
                filename="paper.pdf",
                user_id=1,
                status=TaskStatus.COMPLETED,
                original_pdf_path=str(source),
                result_pdf_path=str(chinese),
                result_dual_pdf_path=str(dual),
            )
        )
        session.commit()
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="one@example.com", hashed_password="unused")
    app.include_router(create_reader_router(reading))
    client = TestClient(app)
    bundle = client.get("/api/reader/tasks/paper").json()
    service = reading.synced_reader
    original = next(v for v in service.versions(bundle["document_id"]) if v.kind == "original")
    service.snapshot(
        bundle["document_id"], "simple", pdf_bytes(SIMPLE), Path(original.path).parent, json.loads(original.index_json)
    )
    bundle = client.get(f"/api/reader/documents/{bundle['document_id']}").json()
    return SimpleNamespace(
        client=client, app=app, engine=engine, service=service, reading=reading, bundle=bundle, source=source
    )


def annotation_body(reader, kind="chinese", operation="create", base=0):
    version = next(v for v in reader.bundle["versions"] if v["kind"] == kind)
    index = json.loads(reader.service.version(reader.bundle["document_id"], version["id"]).index_json)
    rects = char_rects(index["units"][0]["chars"])
    return {
        "operation_id": operation,
        "base_revision": base,
        "version_id": version["id"],
        "data": {
            "id": "native-1",
            "type": 9,
            "pageIndex": 0,
            "rect": union(rects),
            "segmentRects": rects,
            "strokeColor": "#ffee66",
            "opacity": 0.5,
        },
    }


def url(reader, annotation_id="annotation1"):
    return f"/api/reader/documents/{reader.bundle['document_id']}/annotations/{annotation_id}"


def saved(reader):
    return reader.client.get(f"/api/reader/documents/{reader.bundle['document_id']}").json()["annotations"][0]


def test_archiving_legacy_highlights_repairs_duplicate_ids_without_moving_marks(reader, tmp_path):
    with fitz.open() as doc:
        for i in range(2):
            page = doc.new_page()
            page.insert_text((50, 100 + i * 100), f"Important finding on page {i + 1}.")
            mark = page.add_highlight_annot(page.search_for("Important finding"))
            mark.set_info(content=f"finding {i + 1}", title="method_innovation")
            mark.update()
        before = doc.tobytes()
        original_marks = [(a.info, a.vertices, a.colors, a.opacity) for p in doc for a in p.annots()]
        assert original_marks[0][0]["id"] == original_marks[1][0]["id"]
    document_id = reader.bundle["document_id"]
    version = reader.service.snapshot(document_id, "chinese", before, tmp_path)
    # The same old file must resolve to the same repaired revision on every open.
    assert reader.service.snapshot(document_id, "chinese", before, tmp_path).id == version.id
    repaired = Path(version.path).read_bytes()
    with fitz.open(stream=repaired, filetype="pdf") as doc:
        marks = [(a.info, a.vertices, a.colors, a.opacity) for p in doc for a in p.annots()]
        assert len({info["id"] for info, *_ in marks}) == 2
        for original, current in zip(original_marks, marks, strict=True):
            assert {k: v for k, v in original[0].items() if k != "id"} == {
                k: v for k, v in current[0].items() if k != "id"
            }
            assert original[1:] == current[1:]
    assert reader.service.snapshot(document_id, "chinese", repaired, tmp_path).id == version.id


def test_chinese_annotation_projects_to_all_views_and_both_bilingual_pages(reader):
    response = reader.client.put(url(reader), json=annotation_body(reader))
    assert response.status_code == 200, response.text
    result = saved(reader)
    assert result["quote"] == ZH
    assert result["alignment_status"] == "matched"
    by_kind = {v["kind"]: v["id"] for v in reader.bundle["versions"]}
    assert result["projections"][by_kind["original"]][0]["quote"] == EN
    assert result["projections"][by_kind["simple"]][0]["quote"] == SIMPLE
    assert {p["page"] for p in result["projections"][by_kind["bilingual"]]} == {0, 1}
    with Session(reader.engine) as session:
        assert len(session.exec(select(ReaderAnnotation)).all()) == 1


def add_ai_highlight_to_task(reader):
    with Session(reader.engine) as session:
        task = session.get(Task, "paper")
        path, dual_path = Path(task.result_pdf_path), Path(task.result_dual_pdf_path)
    with fitz.open(path) as pdf:
        page = pdf[0]
        mark = page.add_highlight_annot(page.search_for(ZH))
        mark.set_info(title="key_data", content=ZH)
        mark.set_colors(stroke=(0.7, 1, 0.7))
        mark.set_opacity(0.4)
        mark.update()
        data = pdf.tobytes()
    path.write_bytes(data)
    # A generated bilingual PDF may already contain the same native highlight.
    with fitz.open(reader.source) as en, fitz.open(path) as zh, fitz.open() as dual:
        dual.insert_pdf(en)
        dual.insert_pdf(zh)
        dual_path.write_bytes(dual.tobytes())


def test_embedded_ai_highlights_become_shared_and_sync_all_versions(reader):
    add_ai_highlight_to_task(reader)
    bundle = reader.client.get("/api/reader/tasks/paper").json()
    assert len(bundle["annotations"]) == 1
    mark = saved(reader)
    latest = {
        kind: next(v for v in bundle["versions"] if v["kind"] == kind)
        for kind in ("original", "chinese", "simple", "bilingual")
    }
    assert mark["alignment_status"] == "matched"
    assert mark["source_version_id"] == latest["chinese"]["id"]
    assert mark["quote"] == ZH
    assert mark["data"]["color"] == "#b2ffb2"
    assert mark["data"]["opacity"] == pytest.approx(0.4)
    for kind, quote in [("original", EN), ("simple", SIMPLE)]:
        assert mark["projections"][latest[kind]["id"]][0]["quote"] == quote
    assert {p["page"] for p in mark["projections"][latest["bilingual"]["id"]]} == {0, 1}
    assert mark["id"] in latest["bilingual"]["embedded_annotations"].values()
    assert len(reader.client.get("/api/reader/tasks/paper").json()["annotations"]) == 1


def test_ai_import_preserves_user_edits_and_tombstones_on_reopen(reader):
    add_ai_highlight_to_task(reader)
    reader.client.get("/api/reader/tasks/paper")
    mark = saved(reader)
    data = {**mark["data"], "color": "#ff0000", "contents": "User note"}
    response = reader.client.put(
        url(reader, mark["id"]),
        json={
            "operation_id": "edit-ai",
            "base_revision": mark["revision"],
            "version_id": mark["source_version_id"],
            "data": data,
            "geometry_changed": False,
        },
    )
    assert response.status_code == 200
    reopened = reader.client.get("/api/reader/tasks/paper").json()["annotations"]
    assert len(reopened) == 1
    assert reopened[0]["data"]["color"] == "#ff0000"
    assert reopened[0]["data"]["contents"] == "User note"
    response = reader.client.put(
        url(reader, mark["id"]),
        json={
            "operation_id": "delete-ai",
            "base_revision": reopened[0]["revision"],
            "version_id": mark["source_version_id"],
            "data": data,
            "deleted": True,
        },
    )
    assert response.status_code == 200
    reopened = reader.client.get("/api/reader/tasks/paper").json()["annotations"]
    assert len(reopened) == 1 and reopened[0]["deleted"]


def test_ai_highlights_reach_versions_generated_after_import(reader):
    add_ai_highlight_to_task(reader)
    reader.client.get("/api/reader/tasks/paper")
    mark = saved(reader)

    def generate(*_args):
        return pdf_bytes(SIMPLE + " Extra explanation."), None, None

    reader.reading.reader_processor = SimpleNamespace(_translate_with_pdf2zh=generate)
    assert reader.service.request_build(reader.bundle["document_id"], "simple")
    asyncio.run(reader.service.build(reader.bundle["document_id"], "simple"))
    bundle = reader.service.bundle(reader.bundle["document_id"], 1)
    latest = next(v for v in bundle["versions"] if v["kind"] == "simple")
    current = next(a for a in bundle["annotations"] if a["id"] == mark["id"])
    assert latest["id"] in current["projections"]
    assert current["alignment_status"] == "matched"


def test_ai_import_does_not_adopt_an_ordinary_embedded_user_highlight(reader):
    with Session(reader.engine) as session:
        path = Path(session.get(Task, "paper").result_pdf_path)
    with fitz.open(path) as pdf:
        page = pdf[0]
        mark = page.add_highlight_annot(page.search_for(ZH))
        mark.set_info(title="Reviewer", content="My note")
        data = pdf.tobytes()
    path.write_bytes(data)
    bundle = reader.client.get("/api/reader/tasks/paper").json()
    assert not bundle["annotations"]


def test_imported_ai_bilingual_copy_is_visible_before_semantic_matching(reader):
    add_ai_highlight_to_task(reader)
    with Session(reader.engine) as session:
        task = session.get(Task, "paper")
    bundle = asyncio.run(reader.service.open_task(task, 1))
    mark = bundle["annotations"][0]
    bilingual = next(v for v in bundle["versions"] if v["kind"] == "bilingual")
    assert mark["alignment_status"] == "pending"
    assert mark["projections"][bilingual["id"]][0]["quote"] == ZH


def test_polling_an_open_reader_imports_ai_highlights_without_reopening_task(reader):
    add_ai_highlight_to_task(reader)
    with Session(reader.engine) as session:
        path = Path(session.get(Task, "paper").result_pdf_path)
    original = next(v for v in reader.service.versions(reader.bundle["document_id"]) if v.kind == "original")
    reader.service.snapshot(
        reader.bundle["document_id"],
        "chinese",
        path.read_bytes(),
        Path(original.path).parent,
        json.loads(original.index_json),
    )
    bundle = reader.client.get(f"/api/reader/documents/{reader.bundle['document_id']}").json()
    assert len(bundle["annotations"]) == 1
    # Its first attempt starts on this poll, without the stale-pending delay.
    assert saved(reader)["alignment_status"] == "matched"


def test_import_scheduler_does_not_serialize_every_highlight(reader):
    from fastapi import BackgroundTasks

    async def scenario():
        started, release = [], asyncio.Event()

        async def align(aid, **_):
            started.append(aid)
            await release.wait()

        reader.service.align = align
        background = BackgroundTasks()
        for i in range(10):
            reader.service.schedule_alignment(background, f"ai-{i}")
        running = asyncio.create_task(background())
        try:
            for _ in range(20):
                await asyncio.sleep(0)
            assert len(started) == 3
        finally:
            release.set()
            await running
        assert len(started) == 10
        assert not reader.service._scheduled

    asyncio.run(scenario())


def test_identical_text_with_different_font_metrics_uses_target_rectangles():
    source = pdf_index(pdf_bytes(EN))
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((75, 140), EN, fontsize=16)
        target = pdf_index(pdf.tobytes())
    source["origin_pages"] = target["origin_pages"] = [0]
    rects = locate_quote(source["units"][0], "30% less memory")
    copied = copied_projection(
        source,
        target,
        {
            "type": 9,
            "pageIndex": 0,
            "rect": union(rects),
            "segmentRects": rects,
        },
    )
    assert len(copied) == 1
    assert copied[0]["quote"] == "30% less memory"
    assert copied[0]["rects"] == locate_quote(target["units"][0], "30% less memory")
    assert copied[0]["rects"] != rects


def test_ai_highlight_with_empty_pdf_contents_recovers_selected_text(reader):
    add_ai_highlight_to_task(reader)
    with Session(reader.engine) as session:
        path = Path(session.get(Task, "paper").result_pdf_path)
    with fitz.open(path) as pdf:
        page = pdf[0]
        mark = next(page.annots())
        mark.set_info(content="")
        data = pdf.tobytes()
    path.write_bytes(data)
    bundle = reader.client.get("/api/reader/tasks/paper").json()
    assert len(bundle["annotations"]) == 1
    assert bundle["annotations"][0]["quote"] == ZH


@pytest.mark.parametrize("deleted", [False, True])
def test_ai_import_adopts_previously_edited_native_record(reader, deleted):
    add_ai_highlight_to_task(reader)
    with Session(reader.engine) as session:
        path = Path(session.get(Task, "paper").result_pdf_path)
    original = next(v for v in reader.service.versions(reader.bundle["document_id"]) if v.kind == "original")
    version = reader.service.snapshot(
        reader.bundle["document_id"],
        "chinese",
        path.read_bytes(),
        Path(original.path).parent,
        json.loads(original.index_json),
    )
    data = annotation_body(reader)["data"]
    data.update(id="fitz-A0", contents="Already edited", color="#ff0000")
    with Session(reader.engine) as session:
        session.add(
            ReaderAnnotation(
                id="existing-user-record",
                document_id=reader.bundle["document_id"],
                user_id=1,
                source_version_id=version.id,
                data_json=json.dumps(data),
                quote=ZH,
                deleted=deleted,
            )
        )
        session.commit()
    bundle = reader.client.get("/api/reader/tasks/paper").json()
    assert len(bundle["annotations"]) == 1
    assert bundle["annotations"][0]["id"] == "existing-user-record"
    assert bundle["annotations"][0]["deleted"] == deleted
    assert bundle["annotations"][0]["data"]["color"] == "#ff0000"
    # Aliases survive a process restart too.
    reader.service._ai_imported.clear()
    reader.service._ai_aliases.clear()
    assert len(reader.client.get("/api/reader/tasks/paper").json()["annotations"]) == 1


@pytest.mark.parametrize("parent_ref", ["native-1", "ep_annotation1_0"])
def test_reply_uses_parent_positions_without_matching_icon_text(reader, parent_ref):
    reader.client.put(url(reader), json=annotation_body(reader))
    parent = saved(reader)

    async def unavailable(*_):
        pytest.fail("A reply with a known parent must not call the language model")

    reader.reading.ask_model = unavailable
    body = annotation_body(reader, operation="reply")
    body["data"] = {
        "id": "reply-native",
        "type": 1,
        "pageIndex": 0,
        "rect": {"origin": {"x": 50, "y": 68}, "size": {"width": 24, "height": 24}},
        "contents": "Keep this explanation",
        "inReplyToId": parent_ref,
    }
    reader.client.put(url(reader, "reply"), json=body)
    with Session(reader.engine) as session:
        before = session.get(ReaderAnnotation, "reply")
        source = (before.data_json, before.quote, before.revision, before.geometry_revision)
    reply = next(a for a in reader.service.bundle(reader.bundle["document_id"], 1)["annotations"] if a["id"] == "reply")
    assert reply["alignment_status"] == "matched"
    for version in reader.bundle["versions"]:
        if version["id"] != parent["source_version_id"]:
            assert [m["quote"] for m in reply["projections"][version["id"]]] == [
                m["quote"] for m in parent["projections"][version["id"]]
            ]

    # A corrected parent propagates to existing replies without changing their source.
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
    projections = json.loads(row.projections_json)
    target = next(v for v in reader.bundle["versions"] if v["kind"] == "simple")
    projections.pop(target["id"])
    reader.service._save_alignment(
        row,
        row.geometry_revision,
        reader.service.versions(row.document_id),
        json.loads(row.anchors_json),
        projections,
        "partial",
        "target needs review",
    )
    with Session(reader.engine) as session:
        after = session.get(ReaderAnnotation, "reply")
        assert (after.data_json, after.quote, after.revision, after.geometry_revision) == source
        assert after.alignment_status == "partial"
        assert target["id"] not in json.loads(after.projections_json)


def test_missing_reply_parent_does_not_send_unrelated_icon_text_to_model(reader):
    async def unavailable(*_):
        pytest.fail("An orphan reply must retain its source without guessing from the icon's text")

    reader.reading.ask_model = unavailable
    body = annotation_body(reader, operation="orphan")
    body["data"] = {
        "id": "orphan",
        "type": 1,
        "pageIndex": 0,
        "rect": body["data"]["rect"],
        "contents": "My reply",
        "inReplyToId": "ep_absent_0",
    }
    reader.client.put(url(reader), json=body)
    assert saved(reader)["alignment_status"] == "partial"
    assert saved(reader)["data"]["contents"] == "My reply"


def test_bilingual_copy_is_immediate_even_when_semantic_service_is_unavailable(reader):
    async def unavailable(*_):
        raise RuntimeError("offline")

    reader.reading.ask_model = unavailable
    response = reader.client.put(url(reader), json=annotation_body(reader))
    assert response.status_code == 200
    dual = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "bilingual")
    # The save response must already include the identical Chinese page, without an AI request.
    assert response.json()["projections"][dual][0]["page"] == 1
    assert saved(reader)["projections"][dual][0]["quote"] == ZH


def test_ink_highlighter_snaps_to_text_and_keeps_the_original_stroke(reader):
    body = annotation_body(reader)
    original = body["data"]
    r = original["rect"]
    y = r["origin"]["y"] + r["size"]["height"] / 2
    original.update(
        type=15,
        intent="InkHighlight",
        strokeWidth=14,
        inkList=[
            {
                "points": [
                    {"x": r["origin"]["x"], "y": y},
                    {"x": r["origin"]["x"] + r["size"]["width"], "y": y + 1},
                ]
            }
        ],
    )
    original.pop("segmentRects")
    response = reader.client.put(url(reader), json=body)
    assert response.status_code == 200
    mark = saved(reader)
    assert mark["data"]["type"] == 9
    assert mark["data"]["readerOriginalAppearance"]["inkList"] == original["inkList"]
    assert mark["quote"] == ZH


@pytest.mark.parametrize("mark_type", [9, 10, 11, 12])
@pytest.mark.parametrize("line_count", [1, 2])
def test_new_oversized_text_marks_are_corrected_before_saving_and_extracting_text(reader, mark_type, line_count):
    # Older open tabs still submit PDFium's 28 pt font boxes for 10 pt Chinese
    # text on a 14 pt line pitch. Each box must select only its intended row.
    rows = ["第一行实验结果。", "第二行实验结果。", "第三行不应选中。"]
    with fitz.open() as pdf:
        page = pdf.new_page()
        for i, text in enumerate(rows):
            page.insert_text((50, 80 + i * 14), text, fontname="china-s", fontsize=10)
        version = reader.service.snapshot(
            reader.bundle["document_id"],
            "chinese",
            pdf.tobytes(),
            reader.source.parent,
        )
    index = json.loads(version.index_json)
    segments = []
    for unit in index["units"][:line_count]:
        r = char_rects(unit["chars"])[0]
        center = r["origin"]["y"] + r["size"]["height"] / 2
        segments.append(
            {
                "origin": {"x": r["origin"]["x"], "y": center - 13},
                "size": {"width": r["size"]["width"], "height": 28},
            }
        )
    body = annotation_body(reader)
    body["version_id"] = version.id
    body["data"].update(type=mark_type, rect=union(segments), segmentRects=segments)
    response = reader.client.put(url(reader), json=body)
    assert response.status_code == 200, response.text
    mark = response.json()
    assert mark["quote"] == " ".join(rows[:line_count])
    assert len(mark["data"]["segmentRects"]) == line_count
    assert all(r["size"]["height"] < 14 for r in mark["data"]["segmentRects"])
    assert mark["data"]["readerOriginalAppearance"]["segmentRects"] == segments
    # Server normalization is durable and an idempotent retry does not expand it.
    assert saved(reader)["data"] == mark["data"]
    assert reader.client.put(url(reader), json=body).json()["data"] == mark["data"]


def test_precise_new_text_geometry_is_preserved_by_the_write_guard(reader):
    body = annotation_body(reader)
    r = body["data"]["segmentRects"][0]
    r["origin"]["y"] += 3
    r["size"]["height"] -= 6
    body["data"]["rect"] = union([r])
    response = reader.client.put(url(reader), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["data"] == body["data"]
    assert response.json()["quote"] == ZH


def test_annotation_created_on_bilingual_chinese_page_reaches_both_languages(reader):
    body = annotation_body(reader)
    dual = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "bilingual")
    body["version_id"] = dual
    body["data"]["pageIndex"] = 1
    assert reader.client.put(url(reader), json=body).status_code == 200
    result = saved(reader)
    assert result["alignment_status"] == "matched"
    assert {p["page"] for p in result["projections"][dual]} == {0, 1}
    assert result["source_version_id"] == dual


def test_bilingual_english_reuses_copied_original_anchor_when_phrase_is_repeated(reader):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 80), EN, fontsize=12)
        page.insert_text((50, 140), "Earlier work also uses 30% less memory.", fontsize=12)
        original_bytes = pdf.tobytes()
        with fitz.open(stream=pdf_bytes(ZH, True)) as zh:
            pdf.insert_pdf(zh)
        dual_bytes = pdf.tobytes()
    doc = reader.bundle["document_id"]
    original = reader.service.snapshot(doc, "original", original_bytes, reader.source.parent)
    dual = reader.service.snapshot(doc, "bilingual", dual_bytes, reader.source.parent, json.loads(original.index_json))
    unit = json.loads(original.index_json)["units"][0]
    segments = locate_quote(unit, "30% less memory")
    body = annotation_body(reader)
    body.update(version_id=dual.id)
    body["data"].update(pageIndex=0, rect=union(segments), segmentRects=segments)
    reader.client.put(url(reader), json=body)
    mark = saved(reader)
    assert mark["anchors"] == [unit["id"]]
    chinese = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "chinese")
    assert mark["projections"][chinese]
    # An earlier failed text search must not poison the verified page copy.
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        projections = json.loads(row.projections_json)
        projections[original.id][0]["unmatched_fragments"] = ["stale failed search"]
        row.projections_json = json.dumps(projections)
        row.anchors_json = "[]"
        session.add(row)
        session.commit()
    asyncio.run(reader.service.align("annotation1"))
    mark = saved(reader)
    assert mark["anchors"] == [unit["id"]]
    assert not mark["projections"][original.id][0].get("unmatched_fragments")


def test_full_sentence_without_final_punctuation_does_not_need_phrase_refinement(reader):
    target = "该方法将内存占用降低30%。"
    units = pdf_index(pdf_bytes(target, True))["units"]
    phases = []

    async def respond(_prompt, context):
        request = json.loads(context)
        phases.append(request.get("phase", "match"))
        return {"matches": [{"id": units[0]["id"], "quote": target, "confidence": 0.99}]}

    reader.reading.ask_model = respond
    found = asyncio.run(
        reader.service._match_selection(EN.rstrip("."), [{"quote": EN.rstrip("."), "context": EN}], units)
    )
    assert found and phases == ["match"]


def test_single_letter_from_next_word_does_not_expand_a_translated_highlight(reader):
    selected = "This knowledge exists in abundance, s"
    sentence = selected + "cattered through repositories and papers."
    target = "这些知识大量存在，散布在存储库和论文中。"
    units = pdf_index(pdf_bytes(target, True))["units"]
    requests = []

    async def respond(_prompt, context):
        request = json.loads(context)
        requests.append(request)
        selection = request.get("selection", "This knowledge exists in abundance,")
        text = "这些知识大量存在" if selection.endswith(",") else target
        return {
            "matches": [
                {
                    "id": units[0]["id"],
                    "quote": text,
                    "confidence": 0.99,
                    "source_index": 0,
                    "source_quote": selection,
                }
            ]
        }

    reader.reading.ask_model = respond
    found = asyncio.run(reader.service._match_selection(selected, [{"quote": selected, "context": sentence}], units))
    assert [m["quote"] for m in found] == ["这些知识大量存在"]
    assert found[0]["unmatched_fragments"] == ["s"]
    assert all(r["selection"] == "This knowledge exists in abundance," for r in requests if "selection" in r)


def test_phrase_scope_rejects_support_from_unselected_source_context(reader):
    sentence = "These facts exist everywhere, scattered through papers."
    selected = "These facts exist everywhere"
    target = "这些事实广泛存在，散布在论文中。"
    units = pdf_index(pdf_bytes(target, True))["units"]

    async def respond(_prompt, context):
        return {
            "matches": [
                {"id": units[0]["id"], "quote": target, "confidence": 0.99, "source_index": 0, "source_quote": sentence}
            ]
        }

    reader.reading.ask_model = respond
    found = asyncio.run(reader.service._match_selection(selected, [{"quote": selected, "context": sentence}], units))
    assert found == []


def test_phrase_partition_does_not_claim_complete_coverage_after_dropping_a_qualifier(reader):
    selected = "This knowledge exists in abundance"
    units = pdf_index(pdf_bytes("这些知识存在，散布在论文中。", True))["units"]
    calls = []

    async def respond(_prompt, context):
        calls.append(context)
        request = json.loads(context)
        if request.get("phase"):
            assert "selection" not in request
            return {
                "matches": [
                    {
                        "id": units[0]["id"],
                        "quote": "这些知识存在",
                        "source_index": 0,
                        "source_quote": "This knowledge exists",
                        "confidence": 0.99,
                    }
                ]
            }
        return {"matches": [{"id": units[0]["id"], "quote": "这些知识存在", "confidence": 0.99}]}

    reader.reading.ask_model = respond
    found = asyncio.run(
        reader.service._match_selection(
            selected, [{"quote": selected, "context": selected + ", scattered through papers."}], units
        )
    )
    assert found[0]["unmatched_fragments"] == ["in abundance"]
    assert len(calls) == 1, "Do not delay a grounded partial result for another coverage request"


def test_reordered_translation_keeps_discontiguous_selected_phrases(reader):
    target = "Agents execute larger parts of machine learning research."
    units = pdf_index(pdf_bytes(target))["units"]
    selected = "代理执行机器学习"

    async def respond(_prompt, context):
        request = json.loads(context)
        if request.get("phase") == "phrase_boundaries":
            return {
                "matches": [
                    {
                        "id": units[0]["id"],
                        "quote": "Agents execute",
                        "source_index": 0,
                        "source_quote": "代理执行",
                        "confidence": 0.99,
                    },
                    {
                        "id": units[0]["id"],
                        "quote": "machine learning",
                        "source_index": 0,
                        "source_quote": "机器学习",
                        "confidence": 0.99,
                    },
                    {
                        "id": units[0]["id"],
                        "quote": "research",
                        "source_index": 0,
                        "source_quote": "研究",
                        "confidence": 0.99,
                    },
                ]
            }
        return {"matches": [{"id": units[0]["id"], "quote": target, "confidence": 0.99}]}

    reader.reading.ask_model = respond
    found = asyncio.run(
        reader.service._match_selection(
            selected, [{"quote": selected, "context": selected + "研究的更大部分。"}], units
        )
    )
    assert [m["quote"] for m in found] == ["Agents execute", "machine learning"]


def test_simplified_matching_uses_original_user_selection_even_with_a_broad_english_projection(reader):
    original = next(v for v in reader.service.versions(reader.bundle["document_id"]) if v.kind == "original")
    unit = json.loads(original.index_json)["units"][0]
    body = annotation_body(reader)
    with Session(reader.engine) as session:
        session.add(
            ReaderAnnotation(
                id="source-extent",
                document_id=reader.bundle["document_id"],
                user_id=1,
                source_version_id=body["version_id"],
                data_json=json.dumps(body["data"]),
                quote=ZH,
                anchors_json=json.dumps([unit["id"]]),
                projections_json=json.dumps(
                    {
                        original.id: [
                            {
                                "unit_id": unit["id"],
                                "page": 0,
                                "quote": EN,
                                "rects": char_rects(unit["chars"]),
                                "method": "semantic",
                            }
                        ]
                    }
                ),
            )
        )
        session.commit()
    requests = []
    previous = reader.reading.ask_model

    async def respond(prompt, context):
        request = json.loads(context)
        if any(u["text"] == SIMPLE for u in request["candidates"]):
            requests.append(request)
        return await previous(prompt, context)

    reader.reading.ask_model = respond
    asyncio.run(reader.service.align("source-extent"))
    assert requests and all(r["selection"] == ZH for r in requests)
    with Session(reader.engine) as session:
        assert session.get(ReaderAnnotation, "source-extent").alignment_status == "matched"


def test_partial_english_selection_does_not_repeat_the_same_simplified_request(reader):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 80), EN, fontsize=12)
        page.insert_text((50, 120), "Because it runs faster.", fontsize=12)
        original = reader.service.snapshot(
            reader.bundle["document_id"], "original", pdf.tobytes(), reader.source.parent
        )
    units = json.loads(original.index_json)["units"]
    segments = char_rects(units[0]["chars"]) + locate_quote(units[1], "B")
    body = annotation_body(reader)
    body["version_id"] = original.id
    body["data"].update(rect=union(segments), segmentRects=segments)
    simple_requests = []
    previous = reader.reading.ask_model

    async def respond(prompt, context):
        request = json.loads(context)
        if request.get("phase") == "coverage":
            return {
                "coverage": [
                    {"source_index": 0, "match_indices": [0], "complete": True, "confidence": 0.99},
                    {"source_index": 1, "match_indices": [], "complete": False, "confidence": 0.99},
                ]
            }
        if not request.get("phase") and any(c["text"] == SIMPLE for c in request["candidates"]):
            simple_requests.append(request)
        return await previous(prompt, context)

    reader.reading.ask_model = respond
    reader.client.put(url(reader), json=body)
    mark = saved(reader)
    simple = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "simple")
    assert mark["projections"][simple][0]["quote"] == SIMPLE
    assert mark["projections"][simple][0]["unmatched_fragments"] == ["B"]
    assert mark["alignment_status"] == "partial"
    assert len(simple_requests) == 1


def test_partial_original_mark_stays_partial_on_copied_bilingual_page(reader):
    body = annotation_body(reader, "original")
    index = json.loads(reader.service.version(reader.bundle["document_id"], body["version_id"]).index_json)
    segments = locate_quote(index["units"][0], "30% less memory")
    body["data"].update(rect=union(segments), segmentRects=segments)
    assert reader.client.put(url(reader), json=body).status_code == 200
    dual = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "bilingual")
    result = saved(reader)
    assert result["quote"] == "30% less memory"
    assert [p["quote"] for p in result["projections"][dual] if p["page"] == 0] == ["30% less memory"]


def test_manual_bilingual_position_is_not_expanded_by_automatic_copy(reader):
    reader.client.put(url(reader), json=annotation_body(reader))
    dual = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "bilingual")
    index = json.loads(reader.service.version(reader.bundle["document_id"], dual).index_json)
    segments = locate_quote(index["units"][0], "30%")
    response = reader.client.put(
        url(reader) + "/link",
        json={
            "base_revision": 1,
            "version_id": dual,
            "data": {"id": "manual", "type": 9, "pageIndex": 0, "rect": union(segments), "segmentRects": segments},
        },
    )
    assert response.status_code == 200
    matches = saved(reader)["projections"][dual]
    assert [(p["quote"], p["method"]) for p in matches if p["page"] == 0] == [("30%", "manual")]
    assert any(p["page"] == 1 for p in matches)


def test_idempotent_retry_and_stale_edit_do_not_overwrite_saved_annotation(reader):
    body = annotation_body(reader)
    assert reader.client.put(url(reader), json=body).status_code == 200
    assert reader.client.put(url(reader), json=body).status_code == 200
    with Session(reader.engine) as session:
        assert len(session.exec(select(ReaderOperation)).all()) == 1
    body.update(operation_id="stale")
    body["data"]["contents"] = "A stale edit"
    assert reader.client.put(url(reader), json=body).status_code == 409
    assert not saved(reader)["data"].get("contents")


def test_edit_from_another_view_preserves_source_geometry_and_deletion_is_recoverable(reader):
    body = annotation_body(reader)
    reader.client.put(url(reader), json=body)
    patch = annotation_body(reader, "simple", "comment", 1)
    patch.update(geometry_changed=False)
    patch["data"]["contents"] = "Read the limitations"
    patch["data"]["strokeColor"] = "#55aa66"
    assert reader.client.put(url(reader), json=patch).status_code == 200
    result = saved(reader)
    assert result["source_version_id"] == body["version_id"]
    assert result["data"]["rect"] == body["data"]["rect"]
    assert result["data"]["contents"] == "Read the limitations"
    patch.update(operation_id="delete", base_revision=2, deleted=True)
    assert reader.client.put(url(reader), json=patch).status_code == 200
    assert saved(reader)["deleted"]
    patch.update(operation_id="restore", base_revision=3, deleted=False)
    assert reader.client.put(url(reader), json=patch).status_code == 200
    assert not saved(reader)["deleted"]
    assert saved(reader)["revision"] == 4


def test_missing_or_failed_semantic_alignment_keeps_original_annotation(reader):
    async def unavailable(*_args):
        raise RuntimeError("offline")

    reader.reading.ask_model = unavailable
    assert reader.client.put(url(reader), json=annotation_body(reader)).status_code == 200
    result = saved(reader)
    assert result["quote"] == ZH
    assert result["alignment_status"] == "partial"
    dual = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "bilingual")
    assert set(result["projections"]) == {dual}
    assert result["projections"][dual][0]["method"] == "copied-page"
    assert "已保存" in result["alignment_message"]


def test_model_cannot_invent_a_target_quote(reader):
    async def invalid(_prompt, context):
        candidates = json.loads(context)["candidates"]
        return {"matches": [{"id": candidates[0]["id"], "quote": "An invented result", "confidence": 1}]}

    reader.reading.ask_model = invalid
    reader.client.put(url(reader), json=annotation_body(reader))
    dual = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "bilingual")
    assert set(saved(reader)["projections"]) == {dual}


def test_invalid_combined_model_quote_is_retried_with_validation_feedback(reader):
    calls = []

    async def respond(_prompt, context):
        request = json.loads(context)
        calls.append(request)
        candidates = request["candidates"]
        if len(calls) == 1:
            return {"matches": [{"id": candidates[0]["id"], "quote": EN + " Extra sentence.", "confidence": 0.99}]}
        return {"matches": [{"id": c["id"], "quote": c["text"], "confidence": 0.99} for c in candidates]}

    reader.reading.ask_model = respond
    reader.client.put(url(reader), json=annotation_body(reader))
    assert saved(reader)["alignment_status"] == "matched"
    assert any(c.get("validation_feedback") for c in calls)


def test_sync_drops_extra_model_matches_with_a_different_numeric_result(reader):
    version = reader.service.snapshot(
        reader.bundle["document_id"],
        "original",
        pdf_bytes(EN + "\nThe other result is 30.22%."),
        reader.source.parent,
    )

    async def overmatch(_prompt, context):
        return {
            "matches": [
                {"id": c["id"], "quote": c["text"], "confidence": 0.99} for c in json.loads(context)["candidates"]
            ]
        }

    reader.reading.ask_model = overmatch
    assert reader.client.put(url(reader), json=annotation_body(reader)).status_code == 200
    projections = saved(reader)["projections"][version.id]
    assert [m["quote"] for m in projections] == [EN]


def test_introduction_mark_is_not_matched_to_a_similar_abstract_on_the_previous_page(reader):
    def two_pages(chinese):
        with fitz.open() as pdf:
            for _i in range(2):
                p = pdf.new_page()
                p.insert_text((50, 80), ZH if chinese else EN, fontname="china-s" if chinese else "helv", fontsize=12)
            return pdf.tobytes()

    original = reader.service.snapshot(reader.bundle["document_id"], "original", two_pages(False), reader.source.parent)
    chinese = reader.service.snapshot(
        reader.bundle["document_id"], "chinese", two_pages(True), reader.source.parent, json.loads(original.index_json)
    )
    index = json.loads(chinese.index_json)
    body = annotation_body(reader)
    segments = char_rects(next(u for u in index["units"] if u["page"] == 1)["chars"])
    body["version_id"] = chinese.id
    body["data"].update(pageIndex=1, rect=union(segments), segmentRects=segments)
    assert reader.client.put(url(reader), json=body).status_code == 200
    assert {m["page"] for m in saved(reader)["projections"][original.id]} == {1}


def test_short_selected_phrase_is_matched_with_its_source_sentence_context(reader):
    original = reader.service.snapshot(
        reader.bundle["document_id"],
        "original",
        pdf_bytes("The model's prior is broad but fixed."),
        reader.source.parent,
    )
    chinese = reader.service.snapshot(
        reader.bundle["document_id"],
        "chinese",
        pdf_bytes("模型的先验知识很广泛，但是固定的。", True),
        reader.source.parent,
        json.loads(original.index_json),
    )
    index = json.loads(chinese.index_json)
    segments = locate_quote(index["units"][0], "是固定的")
    body = annotation_body(reader)
    body["version_id"] = chinese.id
    body["data"].update(rect=union(segments), segmentRects=segments)

    async def contextual(_prompt, context):
        request = json.loads(context)
        if "模型的先验知识很广泛" not in json.dumps(request.get("source_context"), ensure_ascii=False):
            return {"matches": []}
        return {
            "matches": [
                {"id": u["id"], "quote": "fixed", "confidence": 0.99, "source_index": 0, "source_quote": "是固定的"}
                for u in request["candidates"]
                if "prior" in u["text"]
            ]
        }

    reader.reading.ask_model = contextual
    assert reader.client.put(url(reader), json=body).status_code == 200
    assert saved(reader)["projections"][original.id][0]["quote"] == "fixed"


def test_reformatted_revision_relocates_verified_words_without_another_model_call(reader):
    assert reader.client.put(url(reader), json=annotation_body(reader)).status_code == 200
    old = saved(reader)
    original = next(v for v in reader.service.versions(reader.bundle["document_id"]) if v.kind == "original")
    with fitz.open() as pdf:
        pdf.new_page().insert_text((180, 240), SIMPLE, fontsize=12)
        revised = reader.service.snapshot(
            reader.bundle["document_id"],
            "simple",
            pdf.tobytes(),
            reader.source.parent,
            json.loads(original.index_json),
        )

    async def unavailable(*_args):
        raise RuntimeError("No model call should be needed for the same words in a new layout")

    reader.reading.ask_model = unavailable
    # Automatic revision discovery reuses verified text; explicit retry requests
    # intentionally recheck automatic matches, even when a prior result exists.
    assert reader.client.get(f"/api/reader/documents/{reader.bundle['document_id']}").status_code == 200
    result = saved(reader)
    projection = result["projections"][revised.id][0]
    assert result["alignment_status"] == "matched"
    assert projection["quote"] == SIMPLE
    assert projection["method"] == "revision-text"
    assert projection["rects"][0]["origin"]["x"] == pytest.approx(180)
    assert projection["rects"][0]["origin"]["y"] > 220
    assert projection["text_anchor"]["text"] == SIMPLE
    assert result["data"] == old["data"]


def test_model_straight_apostrophe_matches_the_pdf_typographic_apostrophe(reader):
    original = reader.service.snapshot(
        reader.bundle["document_id"],
        "original",
        pdf_bytes("The model’s prior is broad but fixed.", True),
        reader.source.parent,
    )

    async def respond(_prompt, context):
        return {
            "matches": [
                {
                    "id": u["id"],
                    "quote": "The model's prior is broad but",
                    "confidence": 0.99,
                    "source_index": 0,
                    "source_quote": "模型的先验知识很广泛但",
                }
                for u in json.loads(context)["candidates"]
                if "prior" in u["text"]
            ]
        }

    reader.reading.ask_model = respond
    body = annotation_body(reader)
    chinese = reader.service.snapshot(
        reader.bundle["document_id"],
        "chinese",
        pdf_bytes("模型的先验知识很广泛但是固定的。", True),
        reader.source.parent,
        json.loads(original.index_json),
    )
    rs = locate_quote(json.loads(chinese.index_json)["units"][0], "模型的先验知识很广泛但")
    body["version_id"] = chinese.id
    body["data"].update(rect=union(rs), segmentRects=rs)
    assert reader.client.put(url(reader), json=body).status_code == 200
    assert saved(reader)["projections"][original.id][0]["quote"] == "The model's prior is broad but"


def test_recorded_paragraph_excludes_similar_claims_elsewhere_on_the_same_page(reader):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 80), "A different experiment uses 30% less memory.", fontsize=12)
        page.insert_text((50, 140), EN, fontsize=12)
        original = reader.service.snapshot(
            reader.bundle["document_id"], "original", pdf.tobytes(), reader.source.parent
        )
    with fitz.open() as pdf:
        pdf.new_page().insert_text((50, 140), ZH, fontname="china-s", fontsize=12)
        chinese = reader.service.snapshot(
            reader.bundle["document_id"],
            "chinese",
            pdf.tobytes(),
            reader.source.parent,
            json.loads(original.index_json),
            [{"source": EN, "target": ZH, "page": "0"}],
        )
    body = annotation_body(reader)
    body["version_id"] = chinese.id
    rs = char_rects(json.loads(chinese.index_json)["units"][0]["chars"])
    body["data"].update(rect=union(rs), segmentRects=rs)
    assert reader.client.put(url(reader), json=body).status_code == 200
    assert [p["quote"] for p in saved(reader)["projections"][original.id]] == [EN]


def test_fragment_matching_trims_unselected_claims_after_finding_the_sentence(reader):
    original = reader.service.snapshot(
        reader.bundle["document_id"],
        "original",
        pdf_bytes("The model is broad but fixed."),
        reader.source.parent,
    )
    chinese = reader.service.snapshot(
        reader.bundle["document_id"],
        "chinese",
        pdf_bytes("模型很广泛但固定不变。", True),
        reader.source.parent,
        json.loads(original.index_json),
    )
    phases = []

    async def respond(_prompt, context):
        request = json.loads(context)
        phases.append(request.get("phase"))
        return {
            "matches": [
                {
                    "id": u["id"],
                    "quote": u["text"],
                    "confidence": 0.99,
                    "source_index": 0,
                    "source_quote": "模型很广泛但",
                }
                for u in request["candidates"]
                if "The model is broad" in u["text"]
            ]
        }

    reader.reading.ask_model = respond
    body = annotation_body(reader)
    body["version_id"] = chinese.id
    rs = locate_quote(json.loads(chinese.index_json)["units"][0], "模型很广泛但")
    body["data"].update(rect=union(rs), segmentRects=rs)
    assert reader.client.put(url(reader), json=body).status_code == 200
    assert "phrase_boundaries" in phases
    assert [p["quote"] for p in saved(reader)["projections"][original.id]] == ["The model is broad but"]


def test_precise_phrase_does_not_get_sent_for_a_second_refinement(reader):
    units = pdf_index(pdf_bytes("The model is broad but fixed."))["units"]
    calls = []

    async def respond(_prompt, context):
        calls.append(json.loads(context))
        return {
            "matches": [
                {
                    "id": units[0]["id"],
                    "quote": "fixed" if len(calls) == 1 else units[0]["text"],
                    "source_index": 0,
                    "source_quote": "是固定的",
                    "confidence": 0.99,
                }
            ]
        }

    reader.reading.ask_model = respond
    result = asyncio.run(
        reader.service._match("是固定的", units, [{"selected": "是固定的", "sentence": "模型很广泛但是固定的。"}])
    )
    assert [p["quote"] for p in result] == ["fixed"]
    assert len(calls) == 1


def test_marked_source_span_extracts_only_the_equivalent_target_phrase(reader):
    import asyncio

    units = pdf_index(pdf_bytes("The model knows many things but cannot change."))["units"]

    async def respond(_prompt, context):
        request = json.loads(context)
        if request.get("phase"):
            assert "selection" not in request
            assert "selected" not in request["source_context"][0]
            return {
                "matches": [
                    {
                        "id": units[0]["id"],
                        "quote": "cannot change",
                        "source_index": 0,
                        "source_quote": "fixed",
                        "confidence": 0.99,
                    }
                ]
            }
        return {"matches": [{"id": units[0]["id"], "quote": units[0]["text"], "confidence": 0.99}]}

    reader.reading.ask_model = respond
    result = asyncio.run(
        reader.service._match(
            "fixed", units, [{"selected": "fixed", "sentence": "The model's prior is broad but fixed."}]
        )
    )
    assert [p["quote"] for p in result] == ["cannot change"]


def test_long_selection_keeps_verified_fragments_visible_when_a_version_omits_a_sentence(reader):
    original = next(v for v in reader.service.versions(reader.bundle["document_id"]) if v.kind == "original")
    source = reader.service.snapshot(
        reader.bundle["document_id"],
        "chinese",
        pdf_bytes(ZH + "这段被省略。", True),
        Path(original.path).parent,
        json.loads(original.index_json),
    )
    index = json.loads(source.index_json)
    segments = [r for u in index["units"] for r in char_rects(u["chars"])]
    body = annotation_body(reader)
    body["version_id"] = source.id
    body["data"].update(rect=union(segments), segmentRects=segments)

    async def respond(_prompt, context):
        request = json.loads(context)
        if request.get("phase") == "coverage":
            return {"coverage": [{"source_index": 0, "match_indices": [0], "complete": True, "confidence": 0.99}]}
        return {
            "matches": []
            if "省略" in request["selection"]
            else [
                {"id": c["id"], "quote": c["text"], "confidence": 0.99}
                for c in request["candidates"]
                if "30%" in c["text"]
            ]
        }

    reader.reading.ask_model = respond
    assert reader.client.put(url(reader), json=body).status_code == 200
    result = saved(reader)
    simple = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "simple")
    assert result["projections"][simple][0]["quote"] == SIMPLE
    assert result["projections"][simple][0]["unmatched_fragments"] == ["这段被省略。"]
    assert result["alignment_status"] == "partial"
    assert "省略" in result["quote"]


def test_old_revision_partial_match_does_not_mark_current_versions_incomplete(reader):
    reader.client.put(url(reader), json=annotation_body(reader))
    old_simple = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "simple")
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        projections = json.loads(row.projections_json)
        projections[old_simple][0]["unmatched_fragments"] = ["old omitted clause"]
        row.projections_json = json.dumps(projections)
        session.add(row)
        session.commit()
    original = next(v for v in reader.service.versions(reader.bundle["document_id"]) if v.kind == "original")
    reader.service.snapshot(
        reader.bundle["document_id"],
        "simple",
        pdf_bytes("The current method uses 30% less memory."),
        Path(original.path).parent,
        json.loads(original.index_json),
    )

    # An explicit historical association is preserved, but does not describe current-view coverage.
    async def respond(_prompt, context):
        request = json.loads(context)
        return {
            "matches": [
                {"id": c["id"], "quote": c["text"], "confidence": 0.99}
                for c in request["candidates"]
                if "current" in c["text"]
            ]
        }

    reader.reading.ask_model = respond
    reader.client.get("/api/reader/tasks/paper")
    assert saved(reader)["alignment_status"] == "matched"
    assert saved(reader)["projections"][old_simple][0]["unmatched_fragments"]


def test_manual_association_is_saved_when_model_is_unavailable(reader):
    async def unavailable(*_args):
        raise RuntimeError("offline")

    reader.reading.ask_model = unavailable
    reader.client.put(url(reader), json=annotation_body(reader))
    target = annotation_body(reader, "original", base=1)
    response = reader.client.put(
        url(reader) + "/link", json={k: target[k] for k in ("base_revision", "version_id", "data")}
    )
    assert response.status_code == 200
    assert saved(reader)["projections"][target["version_id"]][0]["method"] == "manual"


def test_archived_pdfs_and_annotations_survive_task_file_replacement(reader):
    reader.client.put(url(reader), json=annotation_body(reader))
    original = next(v for v in reader.bundle["versions"] if v["kind"] == "original")
    reader.source.write_bytes(pdf_bytes("A replacement source."))
    response = reader.client.get(original["url"])
    assert response.status_code == 200
    with fitz.open(stream=response.content, filetype="pdf") as pdf:
        assert EN in pdf[0].get_text()
    assert saved(reader)["quote"] == ZH
    backup = reader.client.get(f"/api/reader/documents/{reader.bundle['document_id']}/archive")
    assert backup.status_code == 200
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(backup.content)) as archive:
        assert "annotations.json" in archive.namelist()
        assert len([n for n in archive.namelist() if n.endswith(".pdf")]) == 4


def test_different_tasks_for_same_users_source_share_document(reader):
    with Session(reader.engine) as session:
        session.add(
            Task(task_id="same-source", filename="another-name.pdf", user_id=1, original_pdf_path=str(reader.source))
        )
        session.commit()
    other = reader.client.get("/api/reader/tasks/same-source").json()
    assert other["document_id"] == reader.bundle["document_id"]
    with Session(reader.engine) as session:
        assert len(session.exec(select(ReaderDocument)).all()) == 1


def test_other_users_cannot_read_pdf_or_modify_annotations(reader):
    body = annotation_body(reader)
    reader.client.put(url(reader), json=body)
    reader.app.dependency_overrides[get_current_user] = lambda: User(
        id=2, email="two@example.com", hashed_password="unused"
    )
    assert reader.client.get(f"/api/reader/documents/{reader.bundle['document_id']}").status_code == 404
    assert reader.client.get(reader.bundle["versions"][0]["url"]).status_code == 404
    assert reader.client.put(url(reader), json=body).status_code == 404


def test_rejects_invalid_page_without_writing(reader):
    body = annotation_body(reader)
    body["data"]["pageIndex"] = 999
    assert reader.client.put(url(reader), json=body).status_code == 422
    with Session(reader.engine) as session:
        assert not session.exec(select(ReaderAnnotation)).all()


def test_quote_geometry_handles_repeated_substrings_and_cjk():
    index = pdf_index(pdf_bytes(ZH, True))
    assert locate_quote(index["units"][0], "内存占用降低30%")
    repeated = pdf_index(pdf_bytes("memory memory"))["units"][0]
    assert not locate_quote(repeated, "memory")


def test_backup_restores_missing_annotations_and_files_without_overwriting_edits(reader):
    from app.models.reading import ReaderVersion

    reader.client.put(url(reader), json=annotation_body(reader))
    prefix = f"/api/reader/documents/{reader.bundle['document_id']}"
    backup = reader.client.get(prefix + "/archive").content
    original = next(v for v in reader.service.versions(reader.bundle["document_id"]) if v.kind == "original")
    Path(original.path).unlink()
    with Session(reader.engine) as session:
        session.delete(session.get(ReaderAnnotation, "annotation1"))
        simple = next(v for v in reader.service.versions(reader.bundle["document_id"]) if v.kind == "simple")
        session.delete(session.get(ReaderVersion, simple.id))
        session.commit()
    restored = reader.client.post(prefix + "/restore", files={"file": ("backup.zip", backup, "application/zip")})
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored"] == 1
    assert Path(original.path).is_file()
    assert len(reader.service.versions(reader.bundle["document_id"])) == 4
    assert saved(reader)["quote"] == ZH
    change = annotation_body(reader, operation="after-restore", base=1)
    change["data"]["contents"] = "A newer note"
    change["geometry_changed"] = False
    assert reader.client.put(url(reader), json=change).status_code == 200
    assert reader.client.post(prefix + "/restore", files={"file": ("backup.zip", backup)}).json()["skipped"] == 1
    assert saved(reader)["data"]["contents"] == "A newer note"


def test_restore_rejects_tampered_files_before_writing(reader):
    import io
    import zipfile

    prefix = f"/api/reader/documents/{reader.bundle['document_id']}"
    archive = reader.client.get(prefix + "/archive").content
    bad = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive)) as source, zipfile.ZipFile(bad, "w") as target:
        for name in source.namelist():
            target.writestr(name, b"broken" if name.endswith(".pdf") else source.read(name))
    result = reader.client.post(prefix + "/restore", files={"file": ("bad.zip", bad.getvalue())})
    assert result.status_code == 422
    assert reader.client.get(reader.bundle["versions"][0]["url"]).status_code == 200


def test_new_generated_revision_keeps_old_files_and_reprojects_existing_annotations(reader):
    reader.client.put(url(reader), json=annotation_body(reader))
    before = {v.id for v in reader.service.versions(reader.bundle["document_id"])}

    def translate(source, filename, task_id, mode, loop, records):
        assert mode == "simplify"
        records.append({"source": EN, "target": "The method needs 30% less memory.", "page": "0"})
        return (
            pdf_bytes("The method needs 30% less memory."),
            None,
            pdf_bytes("This output is NOT a Chinese bilingual version."),
        )

    reader.reading.reader_processor = SimpleNamespace(_translate_with_pdf2zh=translate)
    response = reader.client.post(f"/api/reader/documents/{reader.bundle['document_id']}/versions/simple")
    assert response.status_code == 202
    versions = reader.service.versions(reader.bundle["document_id"])
    assert before.issubset({v.id for v in versions})
    created = next(v for v in versions if v.id not in before)
    assert created.kind == "simple"
    assert json.loads(created.mappings_json)
    assert created.id in saved(reader)["projections"]
    assert all(Path(v.path).is_file() for v in versions)
    assert len([v for v in versions if v.kind == "bilingual"]) == 1


def test_server_service_restart_recovers_stored_annotations(reader):
    reader.client.put(url(reader), json=annotation_body(reader))
    from app.services.synced_reader import SyncedReader

    recovered = SyncedReader(reader.reading).bundle(reader.bundle["document_id"], 1)
    assert recovered["annotations"][0] == saved(reader)


def test_decimal_multiline_and_two_columns_keep_actual_geometry():
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 70), "The gain is 3.5%. More results.")
        page.insert_text((300, 70), "A separate column.")
        page.insert_text((40, 120), "This sentence spans\ntwo different lines.")
        index = pdf_index(pdf.tobytes())
    unit = next(u for u in index["units"] if "3.5%" in u["text"])
    assert unit["text"] == "The gain is 3.5%."
    line_unit = next(u for u in index["units"] if "sentence spans" in u["text"])
    assert len(locate_quote(line_unit, "sentence spans two different lines")) == 2
    assert max(r["origin"]["x"] for r in locate_quote(unit, "3.5%")) < 300


def test_recorded_translation_uses_bilingual_origin_page_mapping():
    from app.services.reader_geometry import page_correspondence, recorded_mappings

    source = pdf_index(pdf_bytes(EN))
    with (
        fitz.open(stream=pdf_bytes(EN), filetype="pdf") as en,
        fitz.open(stream=pdf_bytes(ZH, True), filetype="pdf") as zh,
        fitz.open() as dual,
    ):
        dual.insert_pdf(en)
        dual.insert_pdf(zh)
        target = pdf_index(dual.tobytes())
    target["origin_pages"] = page_correspondence(source, target, "bilingual")
    mappings = recorded_mappings(source, target, [{"source": EN, "target": ZH, "page": "0"}])
    assert mappings[0]["target_ids"] == [u["id"] for u in target["units"] if u["page"] == 1]


def test_identical_figure_projects_ink_with_scale_but_rejects_rotated_image():
    from app.services.reader_geometry import figure_projection

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 80), False)
    pixmap.clear_with(180)
    png = pixmap.tobytes("png")

    def indexed(bounds, rotation=0):
        with fitz.open() as pdf:
            pdf.new_page().insert_image(fitz.Rect(bounds), stream=png, rotate=rotation)
            index = pdf_index(pdf.tobytes())
            index["origin_pages"] = [0]
            return index

    source = indexed((40, 40, 200, 200))
    target = indexed((80, 80, 400, 400))
    mark = {
        "id": "ink",
        "type": 15,
        "pageIndex": 0,
        "rect": {"origin": {"x": 60, "y": 60}, "size": {"width": 50, "height": 20}},
        "inkList": [{"points": [{"x": 60, "y": 60}, {"x": 110, "y": 80}]}],
    }
    projection = figure_projection(source, target, mark)[0]
    assert projection["geometry"]["inkList"][0]["points"] == [{"x": 120, "y": 120}, {"x": 220, "y": 160}]
    assert not figure_projection(source, indexed((80, 80, 400, 400), 90), mark)


def test_later_task_output_gets_existing_annotations_when_reader_is_reopened(reader):
    reader.client.put(url(reader), json=annotation_body(reader))
    original = next(v for v in reader.service.versions(reader.bundle["document_id"]) if v.kind == "original")
    new_version = reader.service.snapshot(
        reader.bundle["document_id"],
        "simple",
        pdf_bytes("The new version uses 30% less memory."),
        Path(original.path).parent,
        json.loads(original.index_json),
    )
    assert new_version.id not in saved(reader)["projections"]
    reader.client.get("/api/reader/tasks/paper")
    assert new_version.id in saved(reader)["projections"]


def test_manual_association_gives_blank_ink_a_shared_content_anchor(reader):
    body = annotation_body(reader)
    body["data"] = {
        "id": "blank-ink",
        "type": 15,
        "pageIndex": 0,
        "rect": {"origin": {"x": 300, "y": 300}, "size": {"width": 30, "height": 20}},
        "inkList": [{"points": [{"x": 300, "y": 300}, {"x": 330, "y": 320}]}],
    }
    reader.client.put(url(reader), json=body)
    assert not saved(reader)["quote"]
    target = annotation_body(reader, "original", base=1)
    response = reader.client.put(
        url(reader) + "/link", json={k: target[k] for k in ("base_revision", "version_id", "data")}
    )
    assert response.status_code == 200
    result = saved(reader)
    assert result["data"]["inkList"] == body["data"]["inkList"]
    assert result["quote"] == EN
    assert result["alignment_status"] == "matched"
    assert len(result["projections"]) == 3


def test_phrase_refinement_can_restore_missing_negation(reader):
    sentence = "This knowledge exists everywhere, but it is not organized for any particular task."
    candidates = pdf_index(pdf_bytes(sentence))["units"]
    uid = candidates[0]["id"]
    bad = "organized for any particular task"
    correct = "not organized for any particular task"
    calls = []

    async def model(_prompt, context):
        request = json.loads(context)
        calls.append(request.get("phase", "match"))
        if request.get("phase") == "phrase_boundaries":
            return {
                "matches": [{"id": uid, "quote": correct, "source_index": 0, "source_quote": quote, "confidence": 0.99}]
            }
        return {"matches": [{"id": uid, "quote": bad, "confidence": 0.99}]}

    reader.reading.ask_model = model
    quote = "organized for no task in particular"
    context = [{"selected": quote, "sentence": "This knowledge is abundant, yet organized for no task in particular."}]
    result = asyncio.run(reader.service._match(quote, candidates, context))
    assert [r["quote"] for r in result] == [correct]


def test_retry_rechecks_an_existing_wrong_projection(reader):
    assert reader.client.put(url(reader), json=annotation_body(reader)).status_code == 200
    mark = saved(reader)
    simple = next(v for v in reader.bundle["versions"] if v["kind"] == "simple")
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, mark["id"])
        projections = json.loads(row.projections_json)
        projections[simple["id"]][0]["quote"] = "memory"
        row.projections_json = json.dumps(projections)
        session.add(row)
        session.commit()
    calls = []
    previous = reader.reading.ask_model

    async def spy(*args):
        calls.append(1)
        return await previous(*args)

    reader.reading.ask_model = spy
    assert reader.client.post(url(reader) + "/align").status_code == 202
    result = saved(reader)
    assert result["projections"][simple["id"]][0]["quote"] != "memory", "Retry keeps existing wrong match unchanged"


def test_background_retry_preserves_reviewed_extent_but_explicit_retry_rechecks_it(reader):
    reader.client.put(url(reader), json=annotation_body(reader))
    simple = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "simple")
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        projections = json.loads(row.projections_json)
        projections[simple][0].update(method="reviewed", unmatched_fragments=["boundary fragment"])
        row.projections_json = json.dumps(projections)
        session.add(row)
        session.commit()
    calls = []
    previous = reader.reading.ask_model

    async def spy(*args):
        calls.append(args)
        return await previous(*args)

    reader.reading.ask_model = spy
    asyncio.run(reader.service.align("annotation1"))
    assert calls == []
    assert saved(reader)["projections"][simple][0]["method"] == "reviewed"
    asyncio.run(reader.service.align("annotation1", force=True))
    assert calls
    assert saved(reader)["projections"][simple][0]["method"] == "semantic"


def test_partial_match_resumes_after_reopening(reader):
    previous = reader.reading.ask_model

    async def missing_simple(prompt, context):
        request = json.loads(context)
        if any("This method needs" in c["text"] for c in request["candidates"]):
            return {"matches": []}
        return await previous(prompt, context)

    reader.reading.ask_model = missing_simple
    reader.client.put(url(reader), json=annotation_body(reader))
    assert saved(reader)["alignment_status"] == "partial"
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        row.updated_at = datetime.utcnow() - timedelta(hours=1)
        for version in session.exec(select(ReaderVersion)).all():
            version.created_at = datetime.utcnow() - timedelta(hours=2)
            session.add(version)
        session.add(row)
        session.commit()
    reader.reading.ask_model = previous
    # Same state transition as reopening a reader after model service recovers.
    reader.client.get("/api/reader/tasks/paper")
    result = saved(reader)
    assert result["alignment_status"] == "matched", "Partial matches are excluded from resume scheduling"


@pytest.mark.parametrize("pending", [False, True])
def test_automatic_recovery_does_not_fill_the_queue_with_old_partials(reader, pending):
    reader.client.put(url(reader), json=annotation_body(reader))
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        row.alignment_status = "partial"
        row.updated_at = datetime.utcnow() - timedelta(hours=1)
        session.add(row)
        duplicate = ReaderAnnotation(**{**row.model_dump(), "id": "annotation2"})
        session.add(duplicate)
        if pending:
            session.add(ReaderAnnotation(**{**row.model_dump(), "id": "new-mark", "alignment_status": "pending"}))
        for version in session.exec(select(ReaderVersion)).all():
            version.created_at = datetime.utcnow() - timedelta(hours=2)
            session.add(version)
        session.commit()
    scheduled = []
    reader.service.schedule_alignment = lambda _background, aid: scheduled.append(aid)
    assert reader.client.get("/api/reader/tasks/paper").status_code == 200
    assert scheduled == (["new-mark"] if pending else ["annotation1"])


def test_clipped_letter_partial_does_not_repeat_automatic_model_requests(reader):
    reader.client.put(url(reader), json=annotation_body(reader, kind="original"))
    source = reader.service.snapshot(
        reader.bundle["document_id"], "original", pdf_bytes(EN + " Budget is limited."), reader.source.parent
    )
    index = json.loads(source.index_json)
    rects = char_rects(index["units"][0]["chars"]) + char_rects(
        [next(c for c in index["units"][1]["chars"] if c["c"] == "B")]
    )
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        row.source_version_id = source.id
        row.quote = EN + " B"
        row.data_json = json.dumps({**json.loads(row.data_json), "rect": union(rects), "segmentRects": rects})
        projections = json.loads(row.projections_json)
        for parts in projections.values():
            for part in parts:
                part["unmatched_fragments"] = ["B"]
        row.projections_json = json.dumps(projections)
        row.alignment_status = "partial"
        row.updated_at = datetime.utcnow() - timedelta(hours=1)
        session.add(row)
        for version in session.exec(select(ReaderVersion)).all():
            version.created_at = datetime.utcnow() - timedelta(hours=2)
            session.add(version)
        session.commit()
    scheduled = []
    reader.service.schedule_alignment = lambda _background, aid: scheduled.append(aid)
    result = reader.client.get(f"/api/reader/documents/{reader.bundle['document_id']}").json()["annotations"][0]
    assert scheduled == []
    assert result["alignment_status"] == "matched"
    assert result["quote"] == EN + " B"
    assert "未选完整" in result["alignment_message"]


def test_page_context_disambiguates_a_whole_repeated_heading():
    units = [
        {"id": "a", "page": 0, "text": "First trial. "},
        {"id": "b", "page": 0, "text": "Observation and analysis."},
        {"id": "c", "page": 0, "text": "Scores decreased. Second trial. "},
        {"id": "d", "page": 0, "text": "Observation and analysis."},
        {"id": "e", "page": 0, "text": "Scores improved."},
    ]
    anchor = text_anchor(units[3], units[3]["text"], units)
    assert anchor["prefix"].endswith("secondtrial.")
    assert anchor["suffix"].startswith("scoresimproved.")


def test_zero_width_ligature_continuation_survives_copy_and_legacy_anchor():
    from app.services.reader_geometry import selection_parts

    # MuPDF expands the final ff ligature into a painted f and a zero-width f.
    # The latter's center can sit just outside the original highlight quad.
    chars = [
        {"c": "d", "b": [10, 10, 16, 20], "l": 0},
        {"c": "i", "b": [16, 10, 20, 20], "l": 0},
        {"c": "f", "b": [20, 10, 28, 20], "l": 0},
        {"c": "f", "b": [28, 10, 28, 20], "l": 0},
        {"c": "\n", "b": None, "l": 0},
        {"c": "l", "b": [10, 24, 14, 34], "l": 1},
        {"c": "e", "b": [14, 24, 20, 34], "l": 1},
        {"c": "f", "b": [20, 24, 24, 34], "l": 1},
        {"c": "t", "b": [24, 24, 28, 34], "l": 1},
    ]
    unit = {"id": "ligature", "page": 0, "text": "diff\nleft", "chars": chars}
    index = {"units": [unit]}
    annotation = {"pageIndex": 0, "rect": {"origin": {"x": 10, "y": 10}, "size": {"width": 17, "height": 24}}}
    assert selection_parts(index, annotation)[0]["quote"] == "diffleft"
    assert text_anchor(unit, "difleft", [unit])["text"] == "diff\nleft"
    # Geometry evidence is required: never auto-correct an ordinary missing letter.
    ordinary = {**unit, "chars": [{**c, "b": [28, 10, 30, 20]} if i == 3 else c for i, c in enumerate(chars)]}
    assert text_anchor(ordinary, "difleft", [ordinary])["text"] == "difleft"
    multiple = {**unit, "text": "diff\nleftdiff", "chars": chars + chars[:4]}
    assert text_anchor(multiple, "difleftdiff", [multiple])["text"] == "diff\nleftdiff"


def test_reading_repairs_legacy_sentence_only_anchors_without_realigning(reader):
    reader.client.put(url(reader), json=annotation_body(reader))
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        original_data, revision, updated = row.data_json, row.revision, row.updated_at
        projections = json.loads(row.projections_json)
        for parts in projections.values():
            for part in parts:
                part["text_anchor"] = {"text": part["quote"]}
        row.projections_json = json.dumps(projections)
        session.add(row)
        session.commit()
    result = saved(reader)
    assert all(p["text_anchor"]["schema"] == 3 for parts in result["projections"].values() for p in parts)
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        assert (row.data_json, row.revision, row.updated_at) == (original_data, revision, updated)


def test_selection_does_not_silently_drop_second_sentence(reader):
    import fitz

    doc = reader.bundle["document_id"]
    folder = reader.source.parent
    original = reader.service.snapshot(
        doc, "original", pdf_bytes("The method reduces memory. It also runs faster."), folder
    )
    source = json.loads(original.index_json)
    chinese = reader.service.snapshot(
        doc, "chinese", pdf_bytes("该方法减少内存占用。它也运行更快。", True), folder, source
    )
    simple = reader.service.snapshot(
        doc, "simple", pdf_bytes("This method needs less memory. It is also faster."), folder, source
    )
    with fitz.open(original.path) as en, fitz.open(chinese.path) as zh, fitz.open() as both:
        both.insert_pdf(en)
        both.insert_pdf(zh)
        reader.service.snapshot(doc, "bilingual", both.tobytes(), folder, source)

    async def incomplete(_prompt, context):
        candidates = json.loads(context)["candidates"]
        first = next(c for c in candidates if "memory" in c["text"] or "内存" in c["text"])
        return {"matches": [{"id": first["id"], "quote": first["text"], "confidence": 0.99}]}

    reader.reading.ask_model = incomplete
    body = annotation_body(reader)
    rs = [r for u in source["units"] for r in char_rects(u["chars"])]
    body["version_id"] = original.id
    body["data"].update(rect=union(rs), segmentRects=rs)
    assert reader.client.put(url(reader), json=body).status_code == 200
    mark = saved(reader)
    targets = [p["quote"] for p in mark["projections"][simple.id]]
    assert mark["alignment_status"] != "matched" or any(
        "faster" in t for t in targets
    ), "Second sentence absent in target but whole annotation marked complete"


def test_completed_original_projection_is_visible_while_simple_is_running(reader):
    from app.api.reader_routes import AnnotationWrite

    previous = reader.reading.ask_model

    async def scenario():
        reached_simple, release_simple = asyncio.Event(), asyncio.Event()

        async def delayed(prompt, context):
            request = json.loads(context)
            if any("This method needs" in c["text"] for c in request["candidates"]):
                reached_simple.set()
                await release_simple.wait()
            return await previous(prompt, context)

        reader.reading.ask_model = delayed
        await reader.service.mutate(
            reader.bundle["document_id"], 1, "annotation1", AnnotationWrite(**annotation_body(reader))
        )
        alignment = asyncio.create_task(reader.service.align("annotation1"))
        try:
            await asyncio.wait_for(reached_simple.wait(), timeout=2)
            bundle = reader.service.bundle(reader.bundle["document_id"], 1)
            mark = bundle["annotations"][0]
            original = next(v for v in bundle["versions"] if v["kind"] == "original")
            assert (
                original["id"] in mark["projections"]
            ), "Completed original projection is withheld until slowest version finishes"
        finally:
            release_simple.set()
            await alignment

    asyncio.run(scenario())


def test_missing_negation_is_rejected_with_actionable_retry_feedback(reader):
    units = pdf_index(pdf_bytes("The data is not organized for a task."))["units"]
    requests = []

    async def omit_negation(_prompt, context):
        request = json.loads(context)
        if request.get("phase") == "coverage":
            return {"coverage": [{"source_index": 0, "match_indices": [0], "complete": False, "confidence": 0.99}]}
        requests.append(request)
        return {"matches": [{"id": units[0]["id"], "quote": "organized for a task", "confidence": 0.99}]}

    reader.reading.ask_model = omit_negation
    assert asyncio.run(reader.service._match("没有为任务组织", units)) == []
    assert len(requests) == 2
    assert "negation" in requests[1]["validation_feedback"][0]


@pytest.mark.parametrize(
    "source,target",
    [
        ("技能将无指导的试错转变为有指导的执行。", "Skills turn unguided trial and error into guided execution."),
        ("该任务不可能完成。", "This task is impossible to complete."),
    ],
)
def test_lexical_negation_requires_semantic_confirmation_instead_of_an_operator(reader, source, target):
    units = pdf_index(pdf_bytes(target))["units"]
    phases = []

    async def respond(_prompt, context):
        request = json.loads(context)
        phases.append(request.get("phase", "match"))
        if request.get("phase") == "coverage":
            return {"coverage": [{"source_index": 0, "match_indices": [0], "complete": True, "confidence": 0.99}]}
        return {"matches": [{"id": units[0]["id"], "quote": target, "confidence": 0.99}]}

    reader.reading.ask_model = respond
    matches = asyncio.run(reader.service._match(source, units))
    assert [m["quote"] for m in matches] == [target]
    assert phases == ["match", "coverage"]


def test_unsuccessful_alignment_finishes_instead_of_claiming_it_is_still_running(reader):
    async def missing(*_):
        return {"matches": []}

    reader.reading.ask_model = missing
    reader.client.put(url(reader), json=annotation_body(reader))
    assert saved(reader)["alignment_status"] == "partial"


def test_alignment_deadline_retains_completed_projections_and_finishes(reader, monkeypatch):
    monkeypatch.setattr("app.services.synced_reader.ALIGNMENT_TIMEOUT_SECONDS", 0.1, raising=False)

    async def stalled(_prompt, context):
        candidates = json.loads(context)["candidates"]
        if any(u["text"] == SIMPLE for u in candidates):
            await asyncio.Event().wait()
        return {
            "matches": [{"id": u["id"], "quote": u["text"], "confidence": 0.99} for u in candidates if u["text"] == EN]
        }

    reader.reading.ask_model = stalled

    async def scenario():
        from app.api.reader_routes import AnnotationWrite

        await reader.service.mutate(
            reader.bundle["document_id"], 1, "annotation1", AnnotationWrite(**annotation_body(reader))
        )
        await asyncio.wait_for(reader.service.align("annotation1"), 1)

    asyncio.run(scenario())
    result = reader.service.bundle(reader.bundle["document_id"], 1)["annotations"][0]
    assert result["alignment_status"] == "partial"
    assert "超时" in result["alignment_message"]
    assert result["quote"] == ZH and result["projections"]
    versions = {v["kind"]: v["id"] for v in reader.bundle["versions"]}
    assert result["projections"][versions["original"]][0]["quote"] == EN
    assert versions["simple"] not in result["projections"]


def test_waiting_for_an_alignment_worker_does_not_spend_the_matching_deadline(reader, monkeypatch):
    from app.api.reader_routes import AnnotationWrite

    monkeypatch.setattr("app.services.synced_reader.ALIGNMENT_TIMEOUT_SECONDS", 0.05)

    async def scenario():
        await reader.service.mutate(
            reader.bundle["document_id"], 1, "annotation1", AnnotationWrite(**annotation_body(reader))
        )
        async with reader.service._alignment:
            running = asyncio.create_task(reader.service.align("annotation1"))
            await asyncio.sleep(0.1)
        await asyncio.wait_for(running, 1)
        mark = reader.service.bundle(reader.bundle["document_id"], 1)["annotations"][0]
        assert mark["alignment_status"] == "matched"

    asyncio.run(scenario())


def test_stalled_model_request_is_retried_within_the_alignment_budget(reader, monkeypatch):
    monkeypatch.setattr("app.services.synced_reader.MODEL_REQUEST_TIMEOUT_SECONDS", 0.05, raising=False)
    units = pdf_index(pdf_bytes(SIMPLE))["units"]
    calls = []

    async def respond(_prompt, _context, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            await asyncio.Event().wait()
        return {"matches": [{"id": units[0]["id"], "quote": SIMPLE, "confidence": 0.99}]}

    reader.reading.ask_model = ReadingService.ask_model.__get__(reader.reading)
    reader.reading.ai.complete_json = respond

    async def scenario():
        matches = await asyncio.wait_for(reader.service._match(ZH, units), 0.5)
        assert matches[0]["quote"] == SIMPLE
        assert len(calls) == 2

    asyncio.run(scenario())


def test_model_queue_wait_does_not_consume_the_response_timeout(reader, monkeypatch):
    monkeypatch.setattr("app.services.synced_reader.MODEL_REQUEST_TIMEOUT_SECONDS", 0.02)

    async def respond(*_args, **_kwargs):
        return {"ok": True}

    reader.reading.ask_model = ReadingService.ask_model.__get__(reader.reading)
    reader.reading.ai.complete_json = respond

    async def scenario():
        await reader.reading._semaphore.acquire()
        pending = asyncio.create_task(reader.service._ask_model("test", "{}"))
        try:
            await asyncio.sleep(0.08)
            assert not pending.done(), "Request expired before it reached the model"
        finally:
            reader.reading._semaphore.release()
        assert await pending == {"ok": True}

    asyncio.run(scenario())


def test_partial_selection_needs_only_one_grounded_model_response(reader):
    source = "The method uses less memory, and errors appear only after a run."
    selected = "errors appear only after a run"
    units = pdf_index(pdf_bytes("该方法节省内存，错误只有在运行之后才会显现。", True))["units"]
    calls = []

    async def respond(_prompt, context):
        calls.append(json.loads(context))
        return {
            "matches": [
                {
                    "id": units[0]["id"],
                    "quote": "错误只有在运行之后才会显现",
                    "source_index": 0,
                    "source_quote": selected,
                    "confidence": 0.99,
                }
            ]
        }

    reader.reading.ask_model = respond
    found = asyncio.run(reader.service._match_selection(selected, [{"quote": selected, "context": source}], units))
    assert [m["quote"] for m in found] == ["错误只有在运行之后才会显现"]
    assert len(calls) == 1


@pytest.mark.parametrize("compact", [False, True])
def test_discontiguous_source_grammar_is_verified_without_invented_ellipses(reader, compact):
    selected = "只有在预算用完后才会显现"
    units = pdf_index(pdf_bytes("Errors appear only after the budget is spent."))["units"]

    async def respond(_prompt, _context):
        if compact:
            return {
                "alignments": [
                    {
                        "id": units[0]["id"],
                        "source_index": 0,
                        "confidence": 0.99,
                        "phrases": [
                            ["appear only after", ["只有在", "后才会显现"]],
                            ["the budget is spent", ["预算用完"]],
                        ],
                    }
                ]
            }
        return {
            "matches": [
                {
                    "id": units[0]["id"],
                    "quote": "appear only after",
                    "source_index": 0,
                    "source_quotes": ["只有在", "后才会显现"],
                    "confidence": 0.99,
                },
                {
                    "id": units[0]["id"],
                    "quote": "the budget is spent",
                    "source_index": 0,
                    "source_quotes": ["预算用完"],
                    "confidence": 0.99,
                },
            ]
        }

    reader.reading.ask_model = respond
    found = asyncio.run(
        reader.service._match_selection(selected, [{"quote": selected, "context": "错误" + selected}], units)
    )
    assert [m["quote"] for m in found] == ["appear only after", "the budget is spent"]
    assert not any(m.get("unmatched_fragments") for m in found)


def test_repeated_complete_selection_reuses_matching_without_sharing_mutable_results(reader):
    units = pdf_index(pdf_bytes("This is fixed."))["units"]
    calls = []

    async def respond(_prompt, _context):
        calls.append(1)
        return {
            "matches": [
                {
                    "id": units[0]["id"],
                    "quote": "fixed",
                    "confidence": 0.99,
                    "source_index": 0,
                    "source_quotes": ["是固定的"],
                }
            ]
        }

    reader.reading.ask_model = respond

    async def scenario():
        context = [{"selected": "是固定的", "sentence": "模型的知识是固定的。"}]
        first = await reader.service._match("是固定的", units, context)
        first[0]["quote"] = "client mutation"
        second = await reader.service._match("是固定的", units, context)
        assert second[0]["quote"] == "fixed"
        assert len(calls) == 1

    asyncio.run(scenario())


def test_different_marks_in_the_same_sentence_reuse_alignment_after_restart(reader):
    from app.services.synced_reader import SyncedReader

    units = pdf_index(pdf_bytes("The model is broad, but stays fixed."))["units"]
    sentence = "模型很广泛，但保持固定。"
    calls = []

    async def respond(_prompt, _context):
        calls.append(1)
        return {
            "matches": [
                {"id": units[0]["id"], "source_index": 0, "confidence": 0.99, "quote": target, "source_quote": source}
                for source, target in [("模型很广泛", "The model is broad"), ("但", "but"), ("保持固定", "stays fixed")]
            ]
        }

    reader.reading.ask_model = respond

    async def scenario():
        first = await reader.service._match(
            "模型很广泛",
            units,
            [{"selected": "模型很广泛", "sentence": sentence}],
            document_id=reader.bundle["document_id"],
        )
        assert [m["quote"] for m in first] == ["The model is broad"]
        restarted = SyncedReader(reader.reading)
        second = await restarted._match(
            "但保持固定",
            units,
            [{"selected": "但保持固定", "sentence": sentence}],
            document_id=reader.bundle["document_id"],
        )
        assert [m["quote"] for m in second] == ["but", "stays fixed"]
        assert len(calls) == 1

    asyncio.run(scenario())


def test_conjunction_cannot_expand_to_an_unselected_action(reader):
    source = "模型很广泛，而错误会出现。"
    units = pdf_index(pdf_bytes("The model is broad and makes mistakes, and problems appear."))["units"]
    calls = []

    async def respond(_prompt, context):
        calls.append(json.loads(context))
        if len(calls) == 1:
            pairs = [("而", "and makes mistakes"), ("错误会出现", "problems appear")]
        else:
            pairs = [("而错误", "and problems"), ("会出现", "appear")]
        return {
            "matches": [
                {"id": units[0]["id"], "source_index": 0, "confidence": 0.99, "quote": target, "source_quote": text}
                for text, target in pairs
            ]
        }

    reader.reading.ask_model = respond
    result = asyncio.run(
        reader.service._match("而错误会出现", units, [{"selected": "而错误会出现", "sentence": source}])
    )
    assert "makes mistakes" not in " ".join(m["quote"] for m in result)
    assert [m["quote"] for m in result] == ["and problems appear"]
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["document", "selection", "revision", "retry"])
def test_phrase_cache_respects_document_selection_revision_and_retry(reader, change):
    from app.services.synced_reader import SyncedReader

    text = "The model is broad, but stays fixed."
    units = pdf_index(pdf_bytes(text))["units"]
    sentence = "模型很广泛，但保持固定。"
    document_id = reader.bundle["document_id"]
    calls = []

    async def respond(_prompt, context):
        candidates = json.loads(context)["candidates"]
        calls.append(1)
        pairs = [("模型很广泛", "The model is broad"), ("但保持固定", "but stays fixed")]
        if len(calls) > 1 and change == "selection":
            pairs = [("固定", "fixed")]
        return {
            "matches": [
                {
                    "id": candidates[0]["id"],
                    "quote": target,
                    "source_quote": source,
                    "source_index": 0,
                    "confidence": 0.99,
                }
                for source, target in pairs
            ]
        }

    reader.reading.ask_model = respond

    async def scenario():
        nonlocal document_id, units
        context = [{"selected": "模型很广泛", "sentence": sentence}]
        await reader.service._match("模型很广泛", units, context, document_id=document_id)
        assert len(calls) == 1
        selected = "模型很广泛"
        if change == "document":
            document_id = "another-user-document"
            with Session(reader.engine) as session:
                session.add(
                    ReaderDocument(id=document_id, user_id=2, fingerprint="same-paper", title="Other user's PDF")
                )
                session.commit()
        elif change == "selection":
            selected = "固定"  # Cuts through a cached phrase: must obtain narrower evidence.
        elif change == "revision":
            with fitz.open() as pdf:
                pdf.new_page().insert_text((90, 100), text, fontsize=12)
                units = pdf_index(pdf.tobytes())["units"]
        else:
            reader.service._phrases.invalidate(document_id)
        restarted = SyncedReader(reader.reading)
        result = await restarted._match(
            selected, units, [{"selected": selected, "sentence": sentence}], document_id=document_id
        )
        assert len(calls) == 2
        assert [m["quote"] for m in result] == (["fixed"] if change == "selection" else ["The model is broad"])
        if change == "revision":
            assert result[0]["rects"][0]["origin"]["x"] >= 90

    asyncio.run(scenario())


def test_simultaneous_different_selections_share_one_sentence_request(reader):
    units = pdf_index(pdf_bytes("The model is broad, but stays fixed."))["units"]
    sentence = "模型很广泛，但保持固定。"
    calls = []

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def respond(_prompt, _context):
            calls.append(1)
            started.set()
            await release.wait()
            return {
                "matches": [
                    {
                        "id": units[0]["id"],
                        "quote": target,
                        "source_quote": source,
                        "source_index": 0,
                        "confidence": 0.99,
                    }
                    for source, target in [("模型很广泛", "The model is broad"), ("但保持固定", "but stays fixed")]
                ]
            }

        reader.reading.ask_model = respond

        async def match(selected):
            return await reader.service._match(
                selected,
                units,
                [{"selected": selected, "sentence": sentence}],
                document_id=reader.bundle["document_id"],
            )

        first = asyncio.create_task(match("模型很广泛"))
        await started.wait()
        second = asyncio.create_task(match("但保持固定"))
        await asyncio.sleep(0)
        release.set()
        a, b = await asyncio.gather(first, second)
        assert [m["quote"] for m in a] == ["The model is broad"]
        assert [m["quote"] for m in b] == ["but stays fixed"]
        assert len(calls) == 1

    asyncio.run(scenario())


def test_completed_whole_selection_cache_survives_restart(reader):
    from app.services.synced_reader import SyncedReader

    units = pdf_index(pdf_bytes("The model stays fixed."))["units"]
    calls = []

    async def respond(_prompt, _context):
        calls.append(1)
        return {"matches": [{"id": units[0]["id"], "quote": "The model stays fixed.", "confidence": 0.99}]}

    reader.reading.ask_model = respond

    async def scenario():
        selected = "模型保持固定。"
        context = [{"selected": selected, "sentence": selected}]
        first = await reader.service._match(selected, units, context, document_id=reader.bundle["document_id"])
        assert first
        second = await SyncedReader(reader.reading)._match(
            selected, units, context, document_id=reader.bundle["document_id"]
        )
        assert second == first
        assert len(calls) == 1

    asyncio.run(scenario())


def test_force_retry_tombstone_rejects_an_older_inflight_table(reader):
    cache, document_id = reader.service._phrases, reader.bundle["document_id"]
    started = datetime.utcnow()
    cache.put("test-key", document_id, {"matches": ["old"]}, started)
    older_request = datetime.utcnow()
    cache.invalidate(document_id)
    cache.put("test-key", document_id, {"matches": ["stale"]}, older_request)
    assert cache.get("test-key") is None
    cache.put("test-key", document_id, {"matches": ["fresh"]}, datetime.utcnow())
    assert cache.get("test-key") == {"matches": ["fresh"]}


@pytest.mark.parametrize(
    "selected,expected", [("而错误会出现", "and problems appear"), ("错误会出现", "problems appear")]
)
def test_adjacent_connective_is_added_only_when_selected(reader, selected, expected):
    units = pdf_index(pdf_bytes("The model works, and problems appear."))["units"]
    result = asyncio.run(
        reader.service._refine_scope(
            selected,
            [{"selected": selected, "sentence": "模型工作，而错误会出现。"}],
            units,
            {
                "matches": [
                    {
                        "id": units[0]["id"],
                        "quote": "problems appear",
                        "source_quote": "错误会出现",
                        "source_index": 0,
                        "confidence": 0.99,
                    }
                ]
            },
        )
    )
    assert [m["quote"] for m in result["matches"]] == [expected]
    assert result["scope_unmatched"] == []


@pytest.mark.parametrize(
    "text,phrase,expected",
    [
        ("Work, and\nproblems appear.", "problems", "and\n"),
        ("Work and problems appear.", "problems", None),
        ("Brand problems appear.", "problems", None),
        ("Work, and unexpected problems appear.", "problems", None),
        ("工作，而错误会出现。", "错误", "而"),
    ],
)
def test_connective_recovery_requires_an_adjacent_clause_prefix(text, phrase, expected):
    from app.services.reader_geometry import CONNECTIVES, connective_prefix, normalized

    result = connective_prefix(text, normalized(text).index(normalized(phrase)), CONNECTIVES)
    assert (result[2] if result else None) == expected


def test_same_language_connective_is_valid_in_simplified_english(reader):
    units = pdf_index(pdf_bytes("Work, and problems appear."))["units"]
    result = asyncio.run(
        reader.service._refine_scope(
            "and",
            [{"selected": "and", "sentence": "Tasks run, and issues occur."}],
            units,
            {
                "matches": [
                    {"id": units[0]["id"], "quote": "and", "source_quote": "and", "source_index": 0, "confidence": 0.99}
                ]
            },
        )
    )
    assert [m["quote"] for m in result["matches"]] == ["and"]
    assert result["scope_unmatched"] == []


def test_repeated_source_word_is_located_by_the_other_exact_phrase(reader):
    selected = "错误只有在错误配置后才会显现"
    units = pdf_index(pdf_bytes("Mistakes surface only after misconfiguration."))["units"]
    calls = []

    async def respond(_prompt, _context):
        calls.append(1)
        return {
            "alignments": [
                {
                    "id": units[0]["id"],
                    "source_index": 0,
                    "confidence": 0.99,
                    "phrases": [
                        ["Mistakes", ["错误"]],
                        ["surface only after", ["只有在", "后才会显现"]],
                        ["misconfiguration", ["错误配置"]],
                    ],
                }
            ]
        }

    reader.reading.ask_model = respond
    found = asyncio.run(
        reader.service._match_selection(selected, [{"quote": selected, "context": "而" + selected}], units)
    )
    assert [m["quote"] for m in found] == ["Mistakes", "surface only after", "misconfiguration"]
    assert not any(m.get("unmatched_fragments") for m in found)
    assert len(calls) == 1


def test_two_target_phrases_cannot_reuse_the_same_source_word(reader):
    selected = "而错误只有在错误配置后才会显现"
    units = pdf_index(pdf_bytes("and making mistakes, problems surface only after misconfiguration."))["units"]

    async def respond(_prompt, _context):
        return {
            "alignments": [
                {
                    "id": units[0]["id"],
                    "source_index": 0,
                    "confidence": 0.99,
                    "phrases": [
                        ["and making mistakes", ["而错误"]],
                        ["problems surface only after", ["错误只有在", "后才会显现"]],
                        ["misconfiguration", ["错误配置"]],
                    ],
                }
            ]
        }

    reader.reading.ask_model = respond
    found = asyncio.run(
        reader.service._match_selection(selected, [{"quote": selected, "context": "在任务内，" + selected}], units)
    )
    assert [m["quote"] for m in found] == ["misconfiguration"]
    assert found[0]["unmatched_fragments"]


@pytest.mark.parametrize("complete", [False, True])
def test_partial_projection_is_visible_while_semantic_coverage_is_checked(reader, complete):
    from app.api.reader_routes import AnnotationWrite

    async def scenario():
        checking, release = asyncio.Event(), asyncio.Event()
        previous = reader.service._match_selection

        async def match(quote, parts, candidates):
            matches = await previous(quote, parts, candidates)
            if any(u["text"] == SIMPLE for u in candidates):
                for m in matches:
                    m["unmatched_fragments"] = ["源语言语法片段"]
            return matches

        async def coverage(parts, _matches):
            checking.set()
            await release.wait()
            return [] if complete else [p["quote"] for p in parts]

        reader.service._match_selection = match
        reader.service._uncovered_parts = coverage
        await reader.service.mutate(
            reader.bundle["document_id"], 1, "annotation1", AnnotationWrite(**annotation_body(reader))
        )
        task = asyncio.create_task(reader.service.align("annotation1"))
        simple = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "simple")
        try:
            await asyncio.wait_for(checking.wait(), 0.5)
            with Session(reader.engine) as session:
                row = session.get(ReaderAnnotation, "annotation1")
                assert json.loads(row.projections_json)[simple][0]["quote"] == SIMPLE
                assert row.alignment_status == "pending"
        finally:
            release.set()
            await task
        with Session(reader.engine) as session:
            row = session.get(ReaderAnnotation, "annotation1")
            assert row.alignment_status == ("matched" if complete else "partial")
            assert bool(json.loads(row.projections_json)[simple][0].get("unmatched_fragments")) is not complete

    asyncio.run(scenario())


def test_simple_projection_can_finish_before_original_matching(reader):
    from app.api.reader_routes import AnnotationWrite

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        previous = reader.reading.ask_model

        async def respond(prompt, context):
            if any(u["text"] == EN for u in json.loads(context)["candidates"]):
                started.set()
                await release.wait()
            return await previous(prompt, context)

        reader.reading.ask_model = respond
        await reader.service.mutate(
            reader.bundle["document_id"], 1, "annotation1", AnnotationWrite(**annotation_body(reader))
        )
        task = asyncio.create_task(reader.service.align("annotation1"))
        try:
            await asyncio.wait_for(started.wait(), 0.5)
            simple = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "simple")
            for _ in range(30):
                with Session(reader.engine) as session:
                    projections = json.loads(session.get(ReaderAnnotation, "annotation1").projections_json)
                if simple in projections:
                    break
                await asyncio.sleep(0.01)
            assert projections[simple][0]["quote"] == SIMPLE
        finally:
            release.set()
            await task

    asyncio.run(scenario())


def test_slow_chinese_matching_does_not_hold_back_the_simple_version(reader):
    from app.api.reader_routes import AnnotationWrite

    async def scenario():
        chinese_started, simple_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        previous = reader.reading.ask_model

        async def respond(prompt, context):
            candidates = json.loads(context)["candidates"]
            if any(u["text"] == ZH for u in candidates):
                chinese_started.set()
                await release.wait()
            if any(u["text"] == SIMPLE for u in candidates):
                simple_started.set()
            return await previous(prompt, context)

        reader.reading.ask_model = respond
        await reader.service.mutate(
            reader.bundle["document_id"], 1, "annotation1", AnnotationWrite(**annotation_body(reader, kind="original"))
        )
        running = asyncio.create_task(reader.service.align("annotation1"))
        try:
            await asyncio.wait_for(chinese_started.wait(), 1)
            await asyncio.wait_for(simple_started.wait(), 0.3)
            simple = next(v["id"] for v in reader.bundle["versions"] if v["kind"] == "simple")
            for _ in range(20):
                mark = reader.service.bundle(reader.bundle["document_id"], 1)["annotations"][0]
                if simple in mark["projections"]:
                    break
                await asyncio.sleep(0.01)
            assert mark["projections"][simple][0]["quote"] == SIMPLE
        finally:
            release.set()
            await running

    asyncio.run(scenario())


@pytest.mark.parametrize("edit", ["geometry", "delete", "note"])
def test_alignment_deadline_does_not_overwrite_concurrent_edits(reader, monkeypatch, edit):
    from app.api.reader_routes import AnnotationWrite

    monkeypatch.setattr("app.services.synced_reader.ALIGNMENT_TIMEOUT_SECONDS", 0.2)

    async def scenario():
        reached = asyncio.Event()

        async def stalled(*_):
            reached.set()
            await asyncio.Event().wait()

        reader.reading.ask_model = stalled
        body = annotation_body(reader)
        await reader.service.mutate(reader.bundle["document_id"], 1, "annotation1", AnnotationWrite(**body))
        running = asyncio.create_task(reader.service.align("annotation1"))
        await asyncio.wait_for(reached.wait(), 1)
        changed = {
            **body,
            "base_revision": 1,
            "operation_id": "edit-during-timeout",
            "deleted": edit == "delete",
            "geometry_changed": edit == "geometry",
            "data": {**body["data"], "contents": "keep this note"},
        }
        expected = await reader.service.mutate(
            reader.bundle["document_id"], 1, "annotation1", AnnotationWrite(**changed)
        )
        await asyncio.wait_for(running, 1)
        actual = reader.service.bundle(reader.bundle["document_id"], 1)["annotations"][0]
        assert actual["data"] == expected["data"] and actual["revision"] == 2
        assert actual["deleted"] == expected["deleted"]
        assert actual["alignment_status"] == ("partial" if edit == "note" else expected["alignment_status"])
        assert actual["projections"] == expected["projections"]

    asyncio.run(scenario())


def test_split_positive_and_negative_fragments_keep_the_negated_operator(reader):
    units = pdf_index(pdf_bytes("It saves memory. It does not run faster."))["units"]

    async def respond(_prompt, _context):
        return {"matches": [{"id": u["id"], "quote": u["text"], "confidence": 0.99} for u in units]}

    reader.reading.ask_model = respond
    found = asyncio.run(reader.service._match("节省内存，但不会运行得更快。", units))
    assert [m["quote"] for m in found] == [u["text"] for u in units]


def test_merged_sentence_requires_explicit_coverage_of_both_selected_sentences(reader):
    units = pdf_index(pdf_bytes("It saves memory and runs faster."))["units"]
    parts = [{"quote": "它节省内存。"}, {"quote": "它运行更快。"}]

    async def merged(_prompt, context):
        request = json.loads(context)
        if request.get("phase") == "coverage":
            assert [h["text"] for h in request["highlights"]] == [units[0]["text"]]
            return {
                "coverage": [
                    {"source_index": i, "match_indices": [0], "complete": True, "confidence": 0.99} for i in range(2)
                ]
            }
        return {"matches": [{"id": units[0]["id"], "quote": units[0]["text"], "confidence": 0.99}]}

    reader.reading.ask_model = merged
    matches = asyncio.run(reader.service._match_selection(" ".join(p["quote"] for p in parts), parts, units))
    assert len(matches) == 1
    assert not matches[0].get("unmatched_fragments")


def test_coverage_audit_reports_the_actual_missing_sentence(reader):
    units = pdf_index(pdf_bytes("It saves memory."))["units"]
    parts = [{"quote": "它节省内存。"}, {"quote": "它运行更快。"}]

    async def partial(_prompt, context):
        if json.loads(context).get("phase") == "coverage":
            return {
                "coverage": [
                    {"source_index": 0, "match_indices": [0], "complete": True, "confidence": 0.99},
                    {"source_index": 1, "match_indices": [0], "complete": False, "confidence": 0.99},
                ]
            }
        return {"matches": [{"id": units[0]["id"], "quote": units[0]["text"], "confidence": 0.99}]}

    reader.reading.ask_model = partial
    matches = asyncio.run(reader.service._match_selection(" ".join(p["quote"] for p in parts), parts, units))
    assert matches[0]["unmatched_fragments"] == ["它运行更快。"]


def test_forced_retry_preserves_manual_links_source_geometry_and_historical_results(reader):
    reader.client.put(url(reader), json=annotation_body(reader))
    target = annotation_body(reader, "original", base=1)
    reader.client.put(url(reader) + "/link", json={k: target[k] for k in ("base_revision", "version_id", "data")})
    before = saved(reader)
    simple = next(v for v in reader.bundle["versions"] if v["kind"] == "simple")
    original = reader.service.version(reader.bundle["document_id"], target["version_id"])
    latest = reader.service.snapshot(
        reader.bundle["document_id"],
        "simple",
        pdf_bytes("This method needs 30% less memory now."),
        reader.source.parent,
        json.loads(original.index_json),
    )
    reader.client.post(url(reader) + "/align")
    after = saved(reader)
    assert after["data"] == before["data"]
    assert after["revision"] == before["revision"]
    assert after["projections"][target["version_id"]] == before["projections"][target["version_id"]]
    assert after["projections"][simple["id"]] == before["projections"][simple["id"]]
    assert after["projections"][latest.id][0]["quote"].endswith("now.")


@pytest.mark.parametrize("edit", ["delete", "geometry", "style"])
def test_alignment_checkpoints_do_not_overwrite_concurrent_edits(reader, edit):
    from app.api.reader_routes import AnnotationWrite

    previous = reader.reading.ask_model

    async def scenario():
        reached, release = asyncio.Event(), asyncio.Event()

        async def delayed(prompt, context):
            if any("This method needs" in c["text"] for c in json.loads(context)["candidates"]):
                reached.set()
                await release.wait()
            return await previous(prompt, context)

        reader.reading.ask_model = delayed
        body = annotation_body(reader)
        await reader.service.mutate(reader.bundle["document_id"], 1, "annotation1", AnnotationWrite(**body))
        running = asyncio.create_task(reader.service.align("annotation1"))
        try:
            await asyncio.wait_for(reached.wait(), 2)
            changed = {
                **body,
                "operation_id": "edit-during-match",
                "base_revision": 1,
                "deleted": edit == "delete",
                "geometry_changed": edit == "geometry",
                "data": {**body["data"], "contents": "keep my new note", "strokeColor": "#00ff00"},
            }
            expected = await reader.service.mutate(
                reader.bundle["document_id"], 1, "annotation1", AnnotationWrite(**changed)
            )
        finally:
            release.set()
            await running
        actual = reader.service.bundle(reader.bundle["document_id"], 1)["annotations"][0]
        assert actual["revision"] == 2
        assert actual["data"] == expected["data"]
        assert actual["deleted"] == expected["deleted"]
        if edit in {"delete", "geometry"}:
            assert actual["projections"] == expected["projections"]
        else:
            assert actual["alignment_status"] == "matched"

    asyncio.run(scenario())


def test_alignment_scheduler_keeps_force_retry_arriving_during_active_run(reader):
    from fastapi import BackgroundTasks

    async def scenario():
        calls = []
        reached, release = asyncio.Event(), asyncio.Event()

        async def align(_id, *, force=False):
            calls.append(force)
            if len(calls) == 1:
                reached.set()
                await release.wait()

        reader.service.align = align
        background = BackgroundTasks()
        reader.service.schedule_alignment(background, "annotation1")
        running = asyncio.create_task(background())
        try:
            await asyncio.wait_for(reached.wait(), 2)
            duplicate = BackgroundTasks()
            reader.service.schedule_alignment(duplicate, "annotation1", force=True)
            reader.service.schedule_alignment(duplicate, "annotation1")
            assert not duplicate.tasks
        finally:
            release.set()
            await running
        assert calls == [False, True]
        assert not reader.service._scheduled
        assert not reader.service._alignment_requests

    asyncio.run(scenario())


def test_fragment_fallback_cannot_claim_two_sentences_from_one_repeated_wrong_match(reader):
    parts = [{"quote": "它节省内存。"}, {"quote": "它运行更快。"}]
    units = pdf_index(pdf_bytes("It saves memory. It runs faster."))["units"]

    async def misleading(_prompt, context):
        request = json.loads(context)
        if request["selection"] == " ".join(p["quote"] for p in parts):
            return {"matches": []}
        return {"matches": [{"id": units[0]["id"], "quote": units[0]["text"], "confidence": 0.99}]}

    reader.reading.ask_model = misleading
    matches = asyncio.run(reader.service._match_selection(" ".join(p["quote"] for p in parts), parts, units))
    assert len(matches) == 1
    assert matches[0]["unmatched_fragments"]


def test_reader_polling_does_not_decode_frozen_pdf_indexes_again(reader, monkeypatch):
    reader.service.bundle(reader.bundle["document_id"], 1)
    decode = json.loads
    frozen = []

    def count_index(value, *args, **kwargs):
        if isinstance(value, str) and '"units":' in value and '"pages":' in value:
            frozen.append(value)
        return decode(value, *args, **kwargs)

    monkeypatch.setattr("app.services.synced_reader.json.loads", count_index)
    for _ in range(3):
        reader.service.bundle(reader.bundle["document_id"], 1)
    assert frozen == []


def test_repeated_new_marks_reuse_page_indexes_without_reparsing_whole_pdfs(reader, monkeypatch):
    reader.client.put(url(reader), json=annotation_body(reader))
    body = annotation_body(reader, operation="new-second")
    body["data"]["id"] = "new-native-second"
    decode = json.loads
    frozen = []

    def count_index(value, *args, **kwargs):
        if isinstance(value, str) and '"units":' in value and '"pages":' in value:
            frozen.append(value)
        return decode(value, *args, **kwargs)

    monkeypatch.setattr("app.services.synced_reader.json.loads", count_index)
    assert reader.client.put(url(reader, "new-second"), json=body).status_code == 200
    assert frozen == []
    marks = reader.service.bundle(reader.bundle["document_id"], 1)["annotations"]
    assert len(marks) == 2 and all(a["alignment_status"] == "matched" for a in marks)


def test_manual_anchor_on_another_page_still_reaches_its_other_languages(reader):
    def two_pages(text, chinese=False):
        with fitz.open() as pdf:
            pdf.new_page().insert_text((50, 80), "Introduction")
            pdf.new_page().insert_text((50, 80), text, fontname="china-s" if chinese else "helv", fontsize=12)
            return pdf.tobytes()

    doc = reader.bundle["document_id"]
    folder = reader.source.parent / "two-pages"
    original = reader.service.snapshot(doc, "original", two_pages(EN), folder)
    original_index = json.loads(original.index_json)
    reader.service.snapshot(doc, "chinese", two_pages(ZH, True), folder, original_index)
    simple = reader.service.snapshot(doc, "simple", two_pages(SIMPLE), folder, original_index)
    reader.bundle = reader.service.bundle(doc, 1)
    body = annotation_body(reader)
    body["data"] = {
        "id": "blank-ink",
        "type": 15,
        "pageIndex": 0,
        "rect": {"origin": {"x": 300, "y": 300}, "size": {"width": 50, "height": 50}},
        "inkList": [{"points": [{"x": 300, "y": 300}, {"x": 350, "y": 350}]}],
    }
    assert reader.client.put(url(reader), json=body).status_code == 200
    unit = next(u for u in original_index["units"] if u["page"] == 1)
    segments = char_rects(unit["chars"])
    response = reader.client.put(
        url(reader) + "/link",
        json={
            "base_revision": 1,
            "version_id": original.id,
            "data": {"id": "manual", "type": 9, "pageIndex": 1, "rect": union(segments), "segmentRects": segments},
        },
    )
    assert response.status_code == 200
    mark = saved(reader)
    assert mark["projections"][original.id][0]["method"] == "manual"
    assert mark["projections"][simple.id][0]["quote"] == SIMPLE
    assert mark["projections"][simple.id][0]["page"] == 1


def test_server_recovers_after_browser_closes_and_service_restarts(reader):
    from app.models.reading import ReaderAlignmentRetry
    from app.services.reader_recovery import ReaderRecovery

    previous = reader.reading.ask_model

    async def unavailable(*_):
        raise TimeoutError("provider temporarily unavailable")

    reader.reading.ask_model = unavailable
    reader.client.put(url(reader), json=annotation_body(reader))
    with Session(reader.engine) as session:
        record = session.get(ReaderAlignmentRetry, "annotation1")
        assert record.attempts == 1 and record.next_attempt_at
        record.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
        session.add(record)
        session.commit()
    reader.reading.ask_model = previous
    reader.service.recovery = ReaderRecovery(reader.service)
    asyncio.run(reader.service.recovery.run_once())
    with Session(reader.engine) as session:
        assert session.get(ReaderAnnotation, "annotation1").alignment_status == "matched"
        assert session.get(ReaderAlignmentRetry, "annotation1") is None


def test_recovery_budget_does_not_repeat_forever_or_block_other_documents(reader):
    from app.models.reading import ReaderAlignmentRetry

    reader.client.put(url(reader), json=annotation_body(reader))
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        row.alignment_status = "partial"
        session.add(row)
        session.commit()
        for _ in range(4):
            reader.service.recovery.finished(row)
    bundle = reader.service.bundle(reader.bundle["document_id"], 1)
    assert bundle["annotations"][0]["retry_exhausted"]
    scheduled = []
    reader.service.schedule_alignment = lambda _background, aid: scheduled.append(aid)
    asyncio.run(reader.service.recovery.run_once())
    assert scheduled == []
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        row.geometry_revision += 1
        session.add(row)
        session.commit()
    reader.service._scheduled.add("unrelated-document-job")
    asyncio.run(reader.service.recovery.run_once())
    assert scheduled == ["annotation1"]
    with Session(reader.engine) as session:
        assert session.get(ReaderAlignmentRetry, "annotation1").attempts == 4


@pytest.mark.parametrize(
    "source,target",
    [
        ("成本相差约19倍（图9）。", "Cost varies about nineteen-fold (Figure 9)."),
        ("Cost varies about nineteen-fold (Figure 9).", "成本相差约19倍（图9）。"),
    ],
)
def test_digit_and_spelled_out_quantity_are_equivalent(reader, source, target):
    index = pdf_index(pdf_bytes(target, chinese=any("\u4e00" <= c <= "\u9fff" for c in target)))

    async def answer(*_):
        return {"matches": [{"id": index["units"][0]["id"], "quote": target, "confidence": 0.99}]}

    reader.reading.ask_model = answer
    result = asyncio.run(reader.service._match(source, index["units"]))
    assert result and result[0]["quote"] == target


def test_number_word_matching_does_not_round_a_different_value(reader):
    target = "Cost varies nineteen-fold (Figure 9)."
    index = pdf_index(pdf_bytes(target))

    async def answer(*_):
        return {"matches": [{"id": index["units"][0]["id"], "quote": target, "confidence": 0.99}]}

    reader.reading.ask_model = answer
    assert asyncio.run(reader.service._match("成本相差19.1倍（图9）。", index["units"])) == []


def test_settled_document_poll_does_not_reload_each_annotation(reader):
    from sqlalchemy import event

    reader.client.put(url(reader), json=annotation_body(reader))
    with Session(reader.engine) as session:
        row = session.get(ReaderAnnotation, "annotation1")
        for n in range(40):
            session.add(ReaderAnnotation(**{**row.model_dump(), "id": f"copy-{n}"}))
        session.commit()
    queries = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lower().startswith("select readerannotation."):
            queries.append(statement)

    event.listen(reader.engine, "before_cursor_execute", record)
    try:
        bundle = reader.service.bundle(reader.bundle["document_id"], 1)
    finally:
        event.remove(reader.engine, "before_cursor_execute", record)
    assert len(bundle["annotations"]) == 41
    assert len(queries) == 1, "A one-second polling endpoint must read annotations in one batch"

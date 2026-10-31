from fastapi import HTTPException


def validate_pdf(data: bytes, max_pages: int):
    import fitz

    if not data.startswith(b"%PDF-"):
        raise HTTPException(422, "文件不是有效的 PDF")
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            if document.needs_pass or not 0 < document.page_count <= max_pages:
                raise HTTPException(422, f"请上传未加密、最多 {max_pages} 页的 PDF")
    except (fitz.FileDataError, RuntimeError, ValueError) as exc:
        raise HTTPException(422, "PDF 文件损坏或格式不受支持") from exc

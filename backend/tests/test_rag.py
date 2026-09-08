from pathlib import Path

import docx

from app.services.rag import split_text
from app.services.rag import parse_document


def test_parse_markdown_and_txt(tmp_path):
    md = tmp_path / "note.md"
    md.write_text("# 标题\n\n正文内容", encoding="utf-8")
    assert "# 标题" in parse_document(md)


def test_parse_pdf(tmp_path):
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "sample.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 700, "Hello PDF")
    c.save()
    text = parse_document(pdf)
    assert "Hello PDF" in text


def test_parse_docx(tmp_path):
    docx_path = tmp_path / "sample.docx"
    d = docx.Document()
    d.add_paragraph("这是 Word 段落")
    d.save(str(docx_path))
    assert "这是 Word 段落" in parse_document(docx_path)


def test_split_text_returns_nonempty_chunks():
    text = "\n".join(f"第 {i} 段：生活需要一点随机数字 {i} " * 3 for i in range(60))
    chunks = split_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(c.strip() for c in chunks)
    assert sum(len(c) for c in chunks) > len(text) // 2



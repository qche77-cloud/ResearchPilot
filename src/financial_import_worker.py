"""Bounded PDF extraction child. Receives bytes, never URLs or shell commands."""
import io
import json
import sys
from pypdf import PdfReader


def extract(content):
    if not content.startswith(b'%PDF') or len(content) > 12 * 1024 * 1024:
        raise ValueError('请选择不超过 12 MB 的 PDF 文件')
    reader = PdfReader(io.BytesIO(content), strict=False)
    if reader.is_encrypted:
        raise ValueError('请先解除 PDF 加密后再导入')
    if not 1 <= len(reader.pages) <= 400:
        raise ValueError('PDF 须为 1–400 页')
    pages, total = [], 0
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ''
        total += len(text)
        if total > 1800000:
            raise ValueError('PDF 文本过大，请拆分财报文件')
        pages.append(dict(page=i + 1, text=text))
    if total < 100:
        raise ValueError('未读到可用文字；扫描件暂不支持，请导入文字版财报')
    return pages


if __name__ == '__main__':
    try:
        result = {'pages': extract(sys.stdin.buffer.read(12 * 1024 * 1024 + 1))}
    except Exception as exc:
        result = {'error': str(exc)[:240]}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

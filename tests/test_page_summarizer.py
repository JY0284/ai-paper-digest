import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*Swig.*")

import pytest
from pathlib import Path

from inter.utils import get_debug_log_path
import paper_summarizer
from paper_summarizer import (
    build_session,
    resolve_pdf_url,
    download_pdf,
    extract_markdown,
    chunk_text,
    llm_invoke,
    progressive_summary,
)
from paper_summarizer import HumanMessage, AIMessage
import pymupdf4llm


class FakeResponse:
    def __init__(self, content: bytes, status: int = 200):
        self._content = content
        self.status_code = status
        self._headers = {"content-length": str(len(content))}

    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception(f"HTTP {self.status_code}")

    @property
    def headers(self):
        return self._headers

    def iter_content(self, chunk_size):
        yield self._content


class DummyBar:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def update(self, n):
        pass


def test_build_session_no_proxy():
    session = build_session(None)
    assert session.proxies == {}


def test_build_session_with_proxy():
    session = build_session('http://proxy:1234')
    assert session.proxies['http'] == 'http://proxy:1234'
    assert session.proxies['https'] == 'http://proxy:1234'


def test_resolve_pdf_url_direct_pdf():
    url = 'http://example.com/doc.pdf'
    assert resolve_pdf_url(url) == url


def test_resolve_pdf_url_huggingface():
    hf = 'https://huggingface.co/papers/1234.5678'
    expected = 'https://arxiv.org/pdf/1234.5678.pdf'
    assert resolve_pdf_url(hf) == expected


def test_resolve_pdf_url_scrape(monkeypatch):
    html = '<html><body><a href="file.pdf">PDF</a></body></html>'
    class FakeSession:
        def get(self, url, timeout):
            class R:
                def raise_for_status(self): pass
                @property
                def text(self): return html
            return R()

    pdf = resolve_pdf_url('http://foo.com', session=FakeSession())
    assert pdf == 'http://foo.com/file.pdf'


def test_download_pdf(tmp_path, monkeypatch):
    content = b'data'
    fake_session = type('S', (), {'get': lambda self, url, stream, timeout: FakeResponse(content)})()
    monkeypatch.setattr(paper_summarizer, 'tqdm', lambda *args, **kwargs: DummyBar())

    out = download_pdf('http://example.com/x.pdf', output_dir=tmp_path, session=fake_session)
    assert out.exists()
    assert out.read_bytes() == content

    # Second call uses cache
    out2 = download_pdf('http://example.com/x.pdf', output_dir=tmp_path, session=fake_session)
    assert out2 == out


def test_extract_markdown(tmp_path, monkeypatch):
    pdf = tmp_path / 'a.pdf'
    pdf.write_bytes(b'%PDF')
    monkeypatch.setattr(pymupdf4llm, 'to_markdown', lambda p: '# Test')

    md = extract_markdown(pdf, md_dir=tmp_path)
    assert md.exists()
    assert md.read_text(encoding='utf-8') == '# Test'

    # cached
    md2 = extract_markdown(pdf, md_dir=tmp_path)
    assert md2 == md


def test_chunk_text():
    text = 'abcdefghij'
    chunks = chunk_text(text, max_chars=4, overlap_ratio=0.5)
    assert chunks == ['abcd', 'cdef', 'efgh', 'ghij']


def test_llm_invoke(monkeypatch):
    # stub ChatDeepSeek
    class DummyLLM:
        def __init__(self, **kwargs): pass
        def invoke(self, messages): return AIMessage(content='resp')

    monkeypatch.setattr(paper_summarizer, 'ChatDeepSeek', DummyLLM)
    msg = HumanMessage(content='hi')
    resp = llm_invoke([msg], api_key='key')
    assert isinstance(resp, AIMessage)
    assert resp.content == 'resp'


def test_progressive_summary(monkeypatch, tmp_path):
    calls = []
    def fake_llm(messages, api_key=None, **kwargs):
        calls.append(messages)
        # final pass: first message is AIMessage
        if isinstance(messages[0], AIMessage):
            return AIMessage(content='FINAL')
        return AIMessage(content='CHUNK')

    monkeypatch.setattr(paper_summarizer, 'llm_invoke', fake_llm)
    # ensure no existing cache
    debug_dir = Path(get_debug_log_path())
    if debug_dir.exists():
        for f in debug_dir.iterdir(): f.unlink()

    summary, chunks_summary = progressive_summary(['a', 'b'], summary_path=tmp_path/'summary.md', chunk_summary_path=tmp_path/'chunks.md', api_key='key', max_workers=1)
    assert summary == 'FINAL'
    assert chunks_summary == '\n\n'.join(['CHUNK'] * 2)
    # two chunk calls + one final
    assert len(calls) == 3

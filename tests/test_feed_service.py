import os
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*Swig.*")

from pathlib import Path
from types import SimpleNamespace

# Import the module under test – relative import assuming tests run from repo root
import feed_paper_summarizer_service as svc

################################################################################
# Helpers / fixtures
################################################################################

class DummyAIMessage(SimpleNamespace):
    """Mimic the minimal part of langchain_core.messages.AIMessage we rely on."""
    content: str


################################################################################
# _parse_args
################################################################################

def test_parse_args_defaults():
    argv = [
        "https://example.com/rss.xml",
    ]
    args = svc._parse_args(argv)  # type: ignore[attr-defined]
    assert args.rss_url == "https://example.com/rss.xml"
    # Defaults
    assert args.workers == (svc.os.cpu_count() or 4)
    assert args.output == Path("output.md")
    assert args.api_key is None

################################################################################
# _aggregate_summaries
################################################################################

def test_aggregate_summaries(tmp_path: Path):
    # Two fake summary files
    s1 = tmp_path / "2506.00001.md"
    s2 = tmp_path / "2506.00002.md"
    s1.write_text("Summary 1", encoding="utf-8")
    s2.write_text("Summary 2", encoding="utf-8")

    out_file = tmp_path / "aggregate.md"
    svc._aggregate_summaries([s1, s2], out_file, "https://example.com/rss.xml")  # type: ignore[attr-defined]

    output = out_file.read_text(encoding="utf-8")
    # Header present
    assert "# Batch Summary – https://example.com/rss.xml" in output
    # Each individual summary included under its own heading
    assert "## 2506.00001" in output and "Summary 1" in output
    assert "## 2506.00002" in output and "Summary 2" in output

################################################################################
# _summarize_url – success & failure paths
################################################################################

def test_summarize_url_success(monkeypatch, tmp_path: Path):
    """_summarize_url should return a Path when everything works."""
    # Patch paper_summarizer functions used inside _summarize_url
    class DummyPS:
        SUMMARY_DIR = tmp_path
        CHUNKS_SUMMARY_DIR = tmp_path / 'chunks'

        @staticmethod
        def resolve_pdf_url(url):  # noqa: D401
            return "https://example.com/dummy.pdf"

        @staticmethod
        def download_pdf(url):  # noqa: D401
            # Create a fake PDF path inside tmp_dir
            p = tmp_path / "dummy.pdf"
            p.write_bytes(b"%PDF-1.4")
            return p

        @staticmethod
        def extract_markdown(pdf_path):  # noqa: D401
            p = tmp_path / "markdown"
            os.makedirs(p)
            md = p / "dummy.md"
            md.write_text("Some markdown", encoding="utf-8")
            return md

        @staticmethod
        def chunk_text(text):  # noqa: D401
            return [text]

        @staticmethod
        def progressive_summary(
            chunks, summary_path, chunk_summary_path, api_key=None, base_url=None, provider=None, ollama_base_url=None, ollama_model=None
        ):  # noqa: D401
            os.makedirs(DummyPS.CHUNKS_SUMMARY_DIR, exist_ok=True)
            return "the-summary", "the-chunks-summary"

        @staticmethod
        def generate_tags_from_summary(summary, api_key=None, base_url=None, provider=None, ollama_base_url=None, ollama_model=None):  # noqa: D401
            return ["llm", "reasoning"]

    # Inject dummy ps module into svc
    monkeypatch.setattr(svc, "ps", DummyPS)

    out_path, _, _ = svc._summarize_url("https://example.com/paper", api_key="dummy")  # type: ignore[attr-defined]

    assert out_path is not None and out_path.exists()
    assert out_path.read_text(encoding="utf-8") == "the-summary"

    # tags file should be produced alongside summary
    tags_path = tmp_path / "dummy.tags.json"
    assert tags_path.exists()
    import json as _json
    data = _json.loads(tags_path.read_text(encoding="utf-8"))
    assert data.get("tags") == ["llm", "reasoning"]


def test_summarize_url_backfills_tags_on_cached_summary(monkeypatch, tmp_path: Path):
    class DummyPS:
        SUMMARY_DIR = tmp_path
        CHUNKS_SUMMARY_DIR = tmp_path / 'chunks'

        @staticmethod
        def resolve_pdf_url(url):
            return "https://example.com/dummy.pdf"

        @staticmethod
        def download_pdf(url):
            p = tmp_path / "dummy.pdf"
            p.write_bytes(b"%PDF-1.4")
            return p

        @staticmethod
        def extract_markdown(pdf_path):
            p = tmp_path / "markdown"
            os.makedirs(p, exist_ok=True)
            md = p / "dummy.md"
            md.write_text("Some markdown", encoding="utf-8")
            return md

        @staticmethod
        def chunk_text(text):
            return [text]

        @staticmethod
        def generate_tags_from_summary(summary, api_key=None, base_url=None, provider=None, ollama_base_url=None, ollama_model=None):
            return ["cached"]

    # Pre-create cached summary so the service takes the cached path branch
    (tmp_path / "dummy.md").write_text("CACHED SUMMARY TEXT", encoding="utf-8")

    monkeypatch.setattr(svc, "ps", DummyPS)

    out_path, _, _ = svc._summarize_url("https://example.com/paper", api_key="key")  # type: ignore[attr-defined]

    assert out_path == tmp_path / "dummy.md"
    tags_path = tmp_path / "dummy.tags.json"
    assert tags_path.exists()
    import json as _json
    data = _json.loads(tags_path.read_text(encoding="utf-8"))
    assert data.get("tags") == ["cached"]


def test_summarize_url_failure(monkeypatch):
    """_summarize_url should swallow exceptions and return None."""

    class BadPS:
        def resolve_pdf_url(self, url):  # type: ignore[no-self-use]
            raise RuntimeError("boom")

    monkeypatch.setattr(svc, "ps", BadPS())

    result, _, _ = svc._summarize_url("https://bad-url.com")  # type: ignore[attr-defined]
    assert result is None


def test_collect_local_links_prefers_markdown_over_pdfs(monkeypatch, tmp_path: Path):
    # Create dummy project structure for ps paths
    class DummyPS:
        MD_DIR = tmp_path / "markdown"
        PDF_DIR = tmp_path / "papers"

    md = DummyPS.MD_DIR
    pdf = DummyPS.PDF_DIR
    md.mkdir(parents=True, exist_ok=True)
    pdf.mkdir(parents=True, exist_ok=True)

    # Create stems in both places; markdown stems should be returned
    (md / "2506.10101.md").write_text("x", encoding="utf-8")
    (pdf / "2506.20202.pdf").write_bytes(b"%PDF")

    monkeypatch.setattr(svc, "ps", DummyPS)

    links = svc._collect_local_links()  # type: ignore[attr-defined]
    assert links == ["https://arxiv.org/pdf/2506.10101.pdf"]


def test_collect_local_links_falls_back_to_pdfs(monkeypatch, tmp_path: Path):
    class DummyPS:
        MD_DIR = tmp_path / "markdown"
        PDF_DIR = tmp_path / "papers"

    pdf = DummyPS.PDF_DIR
    pdf.mkdir(parents=True, exist_ok=True)
    (pdf / "2506.30303.pdf").write_bytes(b"%PDF")

    monkeypatch.setattr(svc, "ps", DummyPS)

    links = svc._collect_local_links()  # type: ignore[attr-defined]
    assert links == ["https://arxiv.org/pdf/2506.30303.pdf"]


def test_tags_only_run(monkeypatch, tmp_path: Path):
    class DummyPS:
        SUMMARY_DIR = tmp_path

        @staticmethod
        def generate_tags_from_summary(summary, api_key=None, base_url=None, provider=None, ollama_base_url=None, ollama_model=None):
            return ["t1", "t2"]

    monkeypatch.setattr(svc, "ps", DummyPS)

    # Prepare summaries: one with tags, one without
    s1 = tmp_path / "2507.11111.md"
    s2 = tmp_path / "2507.22222.md"
    s1.write_text("S1", encoding="utf-8")
    s2.write_text("S2", encoding="utf-8")
    (tmp_path / "2507.11111.tags.json").write_text('{"tags":["exists"]}', encoding="utf-8")

    total, updated = svc._tags_only_run()  # type: ignore[attr-defined]
    assert total == 2 and updated == 1
    data = __import__('json').loads((tmp_path / "2507.22222.tags.json").read_text(encoding="utf-8"))
    assert data.get("tags") == ["t1", "t2"]

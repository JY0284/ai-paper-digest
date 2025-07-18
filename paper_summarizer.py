"""
paper_summarizer.py – A small CLI tool that reads an academic paper from a URL
and produces a concise summary with DeepSeek-v3 (or any OpenAI-compatible) LLM.

This revision:
- Caches intermediate files (PDF, markdown, chunk summaries)
- Graceful error handling
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pymupdf4llm
import requests
from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_core.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek
from tqdm import tqdm


# ---------------------------------------------------------------------------
# Configuration & constants
# ---------------------------------------------------------------------------
__version__ = "0.2.0"
MODEL_NAME = "deepseek-chat"
CHUNK_LENGTH = 5000
CHUNK_OVERLAP_RATIO = 0.05

DEFAULT_PROXY_URL = "socks5://127.0.0.1:1081"

# Directories for caching
BASE_DIR = Path(__file__).parent
PDF_DIR = BASE_DIR / "papers"
MD_DIR = BASE_DIR / "markdown"
SUMMARY_DIR = BASE_DIR / "summary"
CHUNKS_SUMMARY_DIR = SUMMARY_DIR / "chunks"
for d in (PDF_DIR, MD_DIR, SUMMARY_DIR, CHUNKS_SUMMARY_DIR):
    d.mkdir(exist_ok=True)

_LOG = logging.getLogger("paper_summarizer")


# ---------------------------------------------------------------------------
# Proxy & session
# ---------------------------------------------------------------------------


def build_session(proxy_url: Optional[str] = None) -> requests.Session:
    session = requests.Session()
    if proxy_url:
        _LOG.debug("Using proxy: %s", proxy_url)
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    return session


SESSION = build_session(os.getenv("PROXY_URL", DEFAULT_PROXY_URL))


# ---------------------------------------------------------------------------
# Networking helpers
# ---------------------------------------------------------------------------


def resolve_pdf_url(url: str, session: requests.Session = SESSION) -> str:
    """Return a direct PDF link for *url*."""
    if url.lower().endswith(".pdf"):
        return url

    if "/papers" in url:
        pdf = url.replace("huggingface.co/papers", "arxiv.org/pdf") + ".pdf"
        return pdf

    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        if a["href"].lower().endswith(".pdf"):
            pdf = requests.compat.urljoin(url, a["href"])
            return pdf

    raise ValueError("No PDF link found on page.")


def download_pdf(
    pdf_url: str, output_dir: Path = PDF_DIR, session: requests.Session = SESSION
) -> Path:
    """Download the PDF or skip if already present."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = pdf_url.rstrip("/").split("/")[-1]
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    outpath = output_dir / filename

    if outpath.exists():
        return outpath

    resp = session.get(pdf_url, stream=True, timeout=60)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    with (
        open(outpath, "wb") as f,
        tqdm(
            desc=f"Downloading {filename}",
            total=total,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
        ) as bar,
    ):
        for chunk in resp.iter_content(2048):
            f.write(chunk)
            bar.update(len(chunk))

    return outpath


# ---------------------------------------------------------------------------
# PDF → Markdown
# ---------------------------------------------------------------------------


def extract_markdown(pdf_path: Path, md_dir: Path = MD_DIR) -> Path:
    """Extract markdown text, caching if already done."""
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / (pdf_path.stem + ".md")

    if md_path.exists():
        return md_path

    md_text = pymupdf4llm.to_markdown(str(pdf_path))
    md_path.write_text(md_text, encoding="utf-8")
    return md_path


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str, max_chars: int = CHUNK_LENGTH, overlap_ratio: float = CHUNK_OVERLAP_RATIO
) -> List[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")
    overlap = int(max_chars * overlap_ratio)
    if overlap >= max_chars:
        raise ValueError("overlap must be less than chunk size")

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunks.append(text[start:end])
        start = end - overlap

        if end == len(text):
            break
    return chunks


# ---------------------------------------------------------------------------
# LLM invocation
# ---------------------------------------------------------------------------


def llm_invoke(
    messages: List[BaseMessage], api_key: Optional[str] = None, **kwargs
) -> AIMessage:
    if not api_key:
        api_key = os.getenv("DEEPSEEK_API_KEY")
    llm = ChatDeepSeek(
        model=MODEL_NAME,
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2,
        api_key=api_key,
    )
    return llm.invoke(messages)


def progressive_summary(
    chunks: Iterable[str],
    summary_path: Path,
    chunk_summary_path: Path,
    api_key: Optional[str] = None,
    max_workers: int = 4,
) -> Tuple[str, str]:
    if summary_path.exists():
        _LOG.info(f"Summary cache hit for {summary_path}.")
        return open(summary_path).read(), open(chunk_summary_path).read()

    chunks = list(chunks)

    summaries: List[str] = [None] * len(chunks)

    def _summarize_one(idx: int, chunk: str):
        msg = HumanMessage(
            PromptTemplate.from_file(
                os.path.join("prompts", "chunk_summary.md"), encoding="utf-8"
            ).format(chunk_content=chunk)
        )
        resp = llm_invoke([msg], api_key=api_key)
        return idx, resp.content

    if not chunk_summary_path.exists():
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_summarize_one, i, c): i for i, c in enumerate(chunks)
            }
            for future in tqdm(
                as_completed(futures), total=len(futures), desc="Summarizing"
            ):
                i, summary = future.result()
                summaries[i] = summary
        joined = "\n\n".join(summaries)
    else:
        joined = open(chunk_summary_path, "r").read()

    # Final pass
    final = llm_invoke(
        [
            AIMessage(
                PromptTemplate.from_file(
                    os.path.join("prompts", "summary.md"), encoding="utf-8"
                ).format()
            ),
            HumanMessage(joined),
        ],
        api_key=api_key,
    )

    return final.content, joined


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize an academic paper via DeepSeek-v3 LLM"
    )
    parser.add_argument("url", help="Paper URL (PDF or landing page)")
    parser.add_argument("--api-key", help="DeepSeek/OpenAI API key")
    parser.add_argument("--proxy", help="Proxy URL to use")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.proxy:
        global SESSION  # pylint: disable=global-statement
        SESSION = build_session(args.proxy)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        _LOG.info("Resolving PDF URL for %s", args.url)
        pdf_url = resolve_pdf_url(args.url)
        _LOG.info("PDF URL: %s", pdf_url)

        pdf_path = download_pdf(pdf_url)
        _LOG.info("PDF cached at %s", pdf_path)

        md_path = extract_markdown(pdf_path)
        _LOG.info("Markdown at %s", md_path)

        text = md_path.read_text(encoding="utf-8")
        chunks = chunk_text(text)
        _LOG.info("Split into %d chunks", len(chunks))

        summary_path = SUMMARY_DIR / (pdf_path.stem + ".md")
        summary = progressive_summary(
            chunks, summary_path=summary_path, api_key=args.api_key
        )
        summary_path.write_text(summary.content, encoding="utf-8")
        print("\n" + "=" * 80 + "\nFINAL SUMMARY saved to:\n" + str(summary_path))

    except Exception as e:
        _LOG.error("Error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()

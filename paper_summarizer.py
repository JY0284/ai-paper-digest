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
import json
from pathlib import Path
import time
from typing import Iterable, List, Optional, Tuple
import re

import pymupdf4llm
try:
    import pymupdf as fitz
except ImportError:
    fitz = None
import requests
from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_core.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek
from langchain_ollama import OllamaLLM
from tqdm import tqdm


# ---------------------------------------------------------------------------
# Configuration & constants
# ---------------------------------------------------------------------------
__version__ = "0.2.0"
MODEL_NAME = "deepseek-chat"
CHUNK_LENGTH = 5000
CHUNK_OVERLAP_RATIO = 0.05

DEFAULT_PROXY_URL = "socks5://127.0.0.1:1081"

# LLM Provider configuration
DEFAULT_LLM_PROVIDER = "deepseek"  # "deepseek" or "ollama"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"

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
        _LOG.warning("Using proxy: %s", proxy_url)
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    else:
        _LOG.warning("No proxy configured, using direct connection")
    return session


# Create session without proxy by default
SESSION = build_session()


# ---------------------------------------------------------------------------
# PDF validation helpers
# ---------------------------------------------------------------------------

def _verify_pdf_integrity(pdf_path: Path) -> bool:
    """Verify that a PDF file is complete and valid."""
    try:
        # Check file size is reasonable (at least 1KB)
        if pdf_path.stat().st_size < 1024:
            _LOG.debug("PDF too small to be valid: %s (%d bytes)", pdf_path, pdf_path.stat().st_size)
            return False
        
        # Try to open with PyMuPDF to verify it's a valid PDF
        if fitz:
            try:
                doc = fitz.open(str(pdf_path))
                page_count = len(doc)
                doc.close()
                
                if page_count == 0:
                    _LOG.debug("PDF has no pages: %s", pdf_path)
                    return False
                    
                _LOG.debug("PDF validation successful: %s (%d pages)", pdf_path, page_count)
                return True
                
            except Exception as e:
                _LOG.debug("PDF validation failed with PyMuPDF: %s - %s", pdf_path, e)
                return False
        
        # Fallback: check if file starts with PDF magic number
        with open(pdf_path, 'rb') as f:
            header = f.read(8)
            if header.startswith(b'%PDF-'):
                _LOG.debug("PDF validation successful (magic number): %s", pdf_path)
                return True
            else:
                _LOG.debug("PDF validation failed (no magic number): %s", pdf_path)
                return False
                
    except Exception as e:
        _LOG.debug("PDF validation error: %s - %s", pdf_path, e)
        return False


# ---------------------------------------------------------------------------
# Networking helpers
# ---------------------------------------------------------------------------


def resolve_pdf_url(url: str, session: requests.Session = SESSION) -> str:
    """Return a direct PDF link for *url*."""
    if "huggingface.co/papers" in url:
        pdf = url.replace("huggingface.co/papers", "arxiv.org/pdf") + ".pdf"
        return pdf
    elif "tldr.takara.ai/p" in url:
        pdf = url.replace("tldr.takara.ai/p", "arxiv.org/pdf") + ".pdf"
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
    pdf_url: str, output_dir: Path = PDF_DIR, session: requests.Session = SESSION, max_retries: int = 3
) -> Path:
    """Download the PDF or skip if already present. Ensures complete downloads only."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = pdf_url.rstrip("/").split("/")[-1]
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    outpath = output_dir / filename

    if outpath.exists():
        # Verify existing PDF is complete and valid
        if _verify_pdf_integrity(outpath):
            _LOG.debug("PDF already exists and is valid: %s", outpath)
            return outpath
        else:
            _LOG.warning("Existing PDF appears corrupted, re-downloading: %s", outpath)
            outpath.unlink()  # Remove corrupted file

        # Retry download logic
    last_error = None
    for attempt in range(max_retries):
        if attempt > 0:
            _LOG.info("Retry attempt %d/%d for downloading %s", attempt + 1, max_retries, filename)
            time.sleep(2)  # Brief delay between retries
        
        try:
            return _download_pdf_single_attempt(pdf_url, output_dir, filename, session)
        except Exception as e:
            last_error = e
            _LOG.warning("Download attempt %d failed: %s", attempt + 1, e)
            continue
    
    # All retries failed
    raise RuntimeError(f"Failed to download PDF after {max_retries} attempts. Last error: {last_error}")


def _download_pdf_single_attempt(
    pdf_url: str, output_dir: Path, filename: str, session: requests.Session
) -> Path:
    """Single attempt to download a PDF file."""
    outpath = output_dir / filename
    
    # Download to temporary file first
    temp_path = output_dir / f"{filename}.tmp"
    
    try:
        resp = session.get(pdf_url, stream=True, timeout=60)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded_size = 0
        last_progress_time = time.time()
        
        with (
            open(temp_path, "wb") as f,
            tqdm(
                desc=f"Downloading {filename}",
                total=total,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
            ) as bar,
        ):
            for chunk in resp.iter_content(2048):
                if chunk:  # Filter out keep-alive chunks
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    bar.update(len(chunk))
                    
                    # Check for progress timeout (stalled download)
                    current_time = time.time()
                    if current_time - last_progress_time > 30:  # 30 seconds without progress
                        raise TimeoutError("Download stalled - no progress for 30 seconds")
                    last_progress_time = current_time
        
        # Verify download completeness
        if total > 0 and downloaded_size != total:
            raise ValueError(f"Download incomplete: expected {total} bytes, got {downloaded_size} bytes")
        
        # Verify PDF integrity before moving to final location
        if not _verify_pdf_integrity(temp_path):
            raise ValueError("Downloaded PDF failed integrity check")
        
        # Move temporary file to final location
        temp_path.rename(outpath)
        _LOG.info("PDF downloaded successfully: %s (%d bytes)", outpath, downloaded_size)
        
        return outpath
        
    except Exception as e:
        # Clean up temporary file on any error
        if temp_path.exists():
            temp_path.unlink()
        _LOG.error("Failed to download PDF %s: %s", pdf_url, e)
        raise
    finally:
        # Ensure temporary file is cleaned up
        if temp_path.exists():
            temp_path.unlink()


# ---------------------------------------------------------------------------
# PDF → Markdown
# ---------------------------------------------------------------------------


def extract_markdown(pdf_path: Path, md_dir: Path = MD_DIR, max_retries: int = 3) -> Path:
    """Extract markdown text, caching if already done."""
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / (pdf_path.stem + ".md")

    if md_path.exists():
        return md_path

    # Try multiple PDF processing approaches with retries
    md_text = None
    all_errors = []

    for attempt in range(max_retries):
        if attempt > 0:
            _LOG.info(f"Retry attempt {attempt + 1}/{max_retries} for {pdf_path}")
            import time
            time.sleep(1)  # Brief pause between retries

        errors = []

        # Method 1: Primary - pymupdf4llm
        try:
            md_text = pymupdf4llm.to_markdown(str(pdf_path))
            if md_text and md_text.strip():
                break  # Success!
        except Exception as e:
            error_msg = f"MuPDF error: {e}"
            _LOG.error("Primary PDF processing failed for %s: %s", pdf_path, error_msg)
            errors.append(error_msg)

        # Method 2: Fallback - try with different MuPDF settings
        if not md_text and fitz:
            try:
                doc = fitz.open(str(pdf_path))
                md_text = ""
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    text = page.get_text()
                    md_text += f"## Page {page_num + 1}\n\n{text}\n\n"
                doc.close()
                if md_text and md_text.strip():
                    break  # Success!
            except Exception as e:
                error_msg = f"Fallback MuPDF error: {e}"
                _LOG.error("Fallback PDF processing failed for %s: %s", pdf_path, error_msg)
                errors.append(error_msg)

        # Method 3: Last resort - try extracting raw text
        if not md_text and fitz:
            try:
                doc = fitz.open(str(pdf_path))
                md_text = ""
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    # Try different extraction methods
                    try:
                        text = page.get_text("text")
                    except:
                        text = page.get_text("html")
                        # Basic HTML to text conversion
                        text = re.sub(r'<[^>]+>', '', text)
                    md_text += f"## Page {page_num + 1}\n\n{text}\n\n"
                doc.close()
                if md_text and md_text.strip():
                    break  # Success!
            except Exception as e:
                error_msg = f"Raw text extraction error: {e}"
                _LOG.error("Raw text extraction failed for %s: %s", pdf_path, error_msg)
                errors.append(error_msg)

        all_errors.extend(errors)

    if not md_text or not md_text.strip():
        error_summary = " | ".join(all_errors)
        raise ValueError(f"All PDF processing methods failed for {pdf_path}. Errors: {error_summary}")

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
    messages: List[BaseMessage], 
    api_key: Optional[str] = None, 
    base_url: Optional[str] = None,
    provider: str = DEFAULT_LLM_PROVIDER,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
    **kwargs
) -> AIMessage:
    """Invoke LLM with support for both DeepSeek and Ollama providers."""
    
    if provider.lower() == "ollama":
        # Use Ollama
        if not ollama_base_url:
            ollama_base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        if not ollama_model:
            ollama_model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
            
        _LOG.debug("Using Ollama provider: %s at %s", ollama_model, ollama_base_url)
        
        llm = OllamaLLM(
            model=ollama_model,
            base_url=ollama_base_url,
            temperature=0,
            timeout=120,  # Ollama can be slower
        )
        
        # Convert messages to text for Ollama (simpler interface)
        if len(messages) == 1:
            prompt = messages[0].content
        else:
            # Handle conversation format
            prompt = "\n\n".join([f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}" for m in messages])
        
        response = llm.invoke(prompt)
        
        # Clean up Ollama response to extract only the actual output
        # Ollama may include <think> tags mixed with output, unlike DeepSeek Chat
        cleaned_content = response
        if isinstance(cleaned_content, str):
            # Remove <think>...</think> blocks
            cleaned_content = re.sub(r'<think>.*?</think>', '', cleaned_content, flags=re.DOTALL)
        
        return AIMessage(content=cleaned_content)
        
    else:
        # Use DeepSeek (default)
        if not api_key:
            api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DeepSeek API key required. Set DEEPSEEK_API_KEY environment variable or pass --api-key")
            
        _LOG.debug("Using DeepSeek provider: %s", MODEL_NAME)
        
        llm = ChatDeepSeek(
            model=MODEL_NAME,
            temperature=0,
            max_tokens=None,
            timeout=None,
            max_retries=2,
            api_key=api_key,
            base_url=base_url,
        )
        return llm.invoke(messages)


def progressive_summary(
    chunks: Iterable[str],
    summary_path: Path,
    chunk_summary_path: Path,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    provider: str = DEFAULT_LLM_PROVIDER,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
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
        resp = llm_invoke([msg], api_key=api_key, base_url=base_url, provider=provider, 
                         ollama_base_url=ollama_base_url, ollama_model=ollama_model)
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
        base_url=base_url,
        provider=provider,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
    )

    return final.content, joined


# ---------------------------------------------------------------------------
# Tag generation from summary
# ---------------------------------------------------------------------------


def generate_tags_from_summary(
    summary_text: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    provider: str = DEFAULT_LLM_PROVIDER,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
    max_tags: int = 8,
) -> dict:
    """Generate AI-aware top-level and detailed tags using the LLM.

    Reads prompt from prompts/tags.md. Returns a dict: {"top": [..], "tags": [..]}.
    """
    tmpl = PromptTemplate.from_file(
        os.path.join("prompts", "tags.md"), encoding="utf-8"
    ).format(summary_content=summary_text)

    resp = llm_invoke([HumanMessage(content=tmpl)], api_key=api_key, base_url=base_url, provider=provider,
                     ollama_base_url=ollama_base_url, ollama_model=ollama_model)
    raw = (resp.content or "").strip()

    # Clean up any <think> tags that might appear in Ollama output
    if provider.lower() == "ollama":
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL)

    # Strip fenced code blocks if present, e.g., ```json ... ``` or ``` ... ```
    fenced_match = re.search(r"```(?:json|\w+)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fenced_match:
        raw = fenced_match.group(1).strip()

    # Try strict JSON parse first
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            tags = [str(t).strip() for t in data.get("tags", []) if str(t).strip()]
            top = [str(t).strip() for t in data.get("top", []) if str(t).strip()]
        elif isinstance(data, list):
            # backward compatibility: array treated as detailed tags only
            tags = [str(t).strip() for t in data if str(t).strip()]
            top = []
        else:
            tags, top = [], []
    except Exception:
        # Try to locate a JSON object or array within the text
        obj = re.search(r"\{[\s\S]*\}", raw)
        if obj:
            try:
                data = json.loads(obj.group(0))
                if isinstance(data, dict):
                    tags = [str(t).strip() for t in data.get("tags", []) if str(t).strip()]
                    top = [str(t).strip() for t in data.get("top", []) if str(t).strip()]
                elif isinstance(data, list):
                    tags = [str(t).strip() for t in data if str(t).strip()]
                    top = []
                else:
                    tags, top = [], []
            except Exception:
                tags, top = [], []
        else:
            # Fallback: allow comma/line separated list for detailed tags only
            if raw.startswith("-") or "\n" in raw:
                parts = [p.strip(" -\t") for p in raw.splitlines()]
            else:
                parts = [p.strip() for p in raw.split(",")]
            tags = [p for p in parts if p]
            top = []

    # Normalize and cap
    normalized: List[str] = []
    seen = set()
    for t in tags:
        norm = " ".join(t.split()).lower()
        if norm and norm not in seen:
            seen.add(norm)
            normalized.append(norm)
        if len(normalized) >= max_tags:
            break

    # Ensure a minimum of 3 tags if possible by splitting slashes etc.
    if len(normalized) < 3:
        extras: List[str] = []
        for t in normalized:
            for part in t.replace("/", " ").split():
                if part and part not in seen:
                    seen.add(part)
                    extras.append(part)
                if len(normalized) + len(extras) >= 3:
                    break
            if len(normalized) + len(extras) >= 3:
                break
        normalized.extend(extras)

    # normalize top-level too and ensure subset of allowed set
    allowed_top = {"llm","nlp","cv","ml","rl","agents","systems","theory","robotics","audio","multimodal"}
    top_norm: List[str] = []
    seen_top = set()
    for t in top:
        k = " ".join(str(t).split()).lower()
        if k in allowed_top and k not in seen_top:
            seen_top.add(k)
            top_norm.append(k)

    return {"top": top_norm, "tags": normalized}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize an academic paper via LLM (DeepSeek or Ollama)"
    )
    parser.add_argument("url", help="Paper URL (PDF or landing page)")
    parser.add_argument("--api-key", help="DeepSeek/OpenAI API key")
    parser.add_argument("--base-url", help="Base URL for OpenAI-compatible LLM API (e.g., https://api.openai.com/v1)")
    parser.add_argument("--provider", choices=["deepseek", "ollama"], default=DEFAULT_LLM_PROVIDER,
                       help=f"LLM provider to use (default: {DEFAULT_LLM_PROVIDER})")
    parser.add_argument("--ollama-base-url", default=DEFAULT_OLLAMA_BASE_URL,
                       help=f"Ollama service base URL (default: {DEFAULT_OLLAMA_BASE_URL})")
    parser.add_argument("--ollama-model", default=DEFAULT_OLLAMA_MODEL,
                       help=f"Ollama model name (default: {DEFAULT_OLLAMA_MODEL})")
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
            chunks, summary_path=summary_path, api_key=args.api_key,
            base_url=args.base_url, provider=args.provider, ollama_base_url=args.ollama_base_url, 
            ollama_model=args.ollama_model
        )
        summary_path.write_text(summary.content, encoding="utf-8")
        print("\n" + "=" * 80 + "\nFINAL SUMMARY saved to:\n" + str(summary_path))

    except Exception as e:
        _LOG.error("Error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()

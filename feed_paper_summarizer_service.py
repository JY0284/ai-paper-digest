"""
feed_paper_summarizer_service.py
================================
A lightweight *service* that chains together the two existing building blocks
in this repository:

* ``collect_hf_paper_links_from_rss.py`` – gathers paper URLs from an RSS feed.
* ``paper_summarizer.py`` – downloads & summarizes each paper with DeepSeek.

The service now keeps its own logging **very high‑level** and leaves the fine‑
grained details (PDF caching, chunking, LLM calls, etc.) to the original
modules. This avoids redundant log spam while still giving batch‑level
visibility.

FEATURES:
- Thread-safe logging to prevent log line mixing during concurrent operations
- Extract-only mode to skip LLM processing and just extract PDF text
- Tags-only mode to generate tags for existing summaries
- Graceful error handling and recovery
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import logging.handlers
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple
import re
from glob import glob
from queue import Queue
from threading import Lock

from tqdm import tqdm
import json
import markdown
from feedgen.feed import FeedGenerator
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Local modules – assume we're run from the repo root or installed package
# ---------------------------------------------------------------------------
try:
    from collect_hf_paper_links_from_rss import get_links_from_rss  # type: ignore
    import paper_summarizer as ps  # type: ignore
except ModuleNotFoundError as _e:  # pragma: no cover
    raise SystemExit(
        "❌ Could not import project modules. Run from the repo root or make sure "
        "the package is installed in your environment."
    ) from _e


__version__ = "0.2.0"
_LOG = logging.getLogger("feed_service")

# Global log listener for cleanup
_log_listener = None

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def _setup_logging(debug: bool) -> None:
    """Configure thread-safe logging for the service and silence chatty libraries.
    
    This uses a QueueHandler + QueueListener pattern to prevent log line mixing
    when multiple threads log simultaneously. All worker threads write to a queue,
    and the main thread processes the queue sequentially, ensuring clean output.
    """
    # Create a queue for thread-safe logging
    log_queue = Queue()
    
    # Create a queue handler that workers will use
    queue_handler = logging.handlers.QueueHandler(log_queue)
    
    # Create a console handler for the main thread
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
    )
    
    # Create a queue listener that runs in the main thread
    queue_listener = logging.handlers.QueueListener(
        log_queue, console_handler, respect_handler_level=True
    )
    
    # Start the listener
    queue_listener.start()
    
    # Configure the root logger to use the queue handler
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # Remove any existing handlers
    root_logger.addHandler(queue_handler)
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # Configure our service logger
    _LOG.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # Store the listener globally so we can stop it later
    global _log_listener
    _log_listener = queue_listener

    if not debug:
        class _MuteHttpXFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
                name = record.name or ""
                if name.startswith("httpx") or name.startswith("httpcore"):
                    return False
                msg = record.getMessage()
                if isinstance(msg, str) and (
                    msg.startswith("HTTP Request:") or msg.startswith("HTTP Response:")
                ):
                    return False
                return True

        for handler in logging.getLogger().handlers:
            handler.addFilter(_MuteHttpXFilter())

        noisy_loggers = [
            "httpx",
            "httpcore",
            "urllib3",
            "openai",
            "langchain_core",
            "langchain_community",
            "langchain_deepseek",
            "langchain_ollama",
            "tenacity",
            "asyncio",
        ]
        for name in noisy_loggers:
            logger = logging.getLogger(name)
            # Be strict with network stacks
            if name in ("httpx", "httpcore"):
                logger.setLevel(logging.CRITICAL)
                logger.disabled = True
            else:
                logger.setLevel(logging.WARNING)
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            logger.propagate = False

# Helper – wrap the paper_summarizer pipeline for a single URL
# ---------------------------------------------------------------------------

def extract_first_header(markdown_text):
    match = re.search(r'^##\s+(.+)$', markdown_text, re.MULTILINE)
    if match:
        return match.group(1).replace("**", '').strip()
    return ""

def _summarize_url(
    url: str,
    api_key: Optional[str] = None,
    provider: str = "deepseek",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "qwen2.5:7b",
    max_input_char: int = 50000,
    extract_only: bool = False,
) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    """Run the full summarization pipeline for *url*.

    Returns the Path to the generated summary markdown and the download url for the paper, 
    or *None* on failure. Only very high‑level logs are emitted here – fine‑grained steps are already
    logged inside ``paper_summarizer``.
    """
    if extract_only:
        _LOG.info("📄  Extracting text from %s", url)
    else:
        _LOG.info("📝  Summarizing %s", url)

    try:
        pdf_url = ps.resolve_pdf_url(url)  # type: ignore[attr-defined]
        pdf_path = ps.download_pdf(pdf_url)  # type: ignore[attr-defined]
        md_path = ps.extract_markdown(pdf_path)  # type: ignore[attr-defined]

        text = md_path.read_text(encoding="utf-8")
        paper_subject = extract_first_header(text)

        # If extract_only mode, return the markdown path directly
        if extract_only:
            _LOG.info("✅  Extracted text saved to %s ", md_path)
            return md_path, pdf_url, paper_subject
        text = re.sub(r'\^\[\d+\](.*\n)+', '', text) # remove references
        if max_input_char > 0:
            text = text[:max_input_char]

        chunks = ps.chunk_text(text)  # type: ignore[attr-defined]

        f_name = pdf_path.stem + ".md"
        summary_path = ps.SUMMARY_DIR / f_name  # type: ignore[attr-defined]
        if summary_path.exists():
            _LOG.warning(f"{summary_path} existed")
            # Ensure tags exist even if summary already cached
            try:
                tags_path = ps.SUMMARY_DIR / (pdf_path.stem + ".tags.json")  # type: ignore[attr-defined]
                if not tags_path.exists():
                    _LOG.info("🏷️  Backfilling tags for %s…", pdf_path.stem)
                    summary_text = summary_path.read_text(encoding="utf-8", errors="ignore")
                    tag_raw = ps.generate_tags_from_summary(summary_text, api_key=api_key, 
                                                          provider=provider, ollama_base_url=ollama_base_url, 
                                                          ollama_model=ollama_model)  # type: ignore[attr-defined]
                    tag_obj = tag_raw if isinstance(tag_raw, dict) else {"tags": list(tag_raw or []), "top": []}
                    tags_path.write_text(json.dumps(tag_obj, ensure_ascii=False, indent=2), encoding="utf-8")
                    _LOG.info("✅  Backfilled %d tag(s) for %s", len(tag_obj.get("tags", [])), pdf_path.stem)
            except Exception as exc:
                _LOG.exception("Failed to backfill tags for %s: %s", pdf_path.stem, exc)
            return summary_path, pdf_url, paper_subject
        chunks_summary_out_path = ps.CHUNKS_SUMMARY_DIR / f_name
        logging.info(f"Start summarizing {md_path}...")
        summary, chunks_summary = ps.progressive_summary(  # type: ignore[attr-defined]
            chunks, summary_path=summary_path, chunk_summary_path=chunks_summary_out_path, api_key=api_key,
            provider=provider, ollama_base_url=ollama_base_url, ollama_model=ollama_model
        )

        chunks_summary_out_path.write_text(chunks_summary, encoding="utf-8")
        summary_path.write_text(summary, encoding="utf-8")

        # Generate and persist tags alongside the summary
        try:
            _LOG.info("🏷️  Generating tags for %s…", pdf_path.stem)
            tag_raw = ps.generate_tags_from_summary(summary, api_key=api_key, 
                                                  provider=provider, ollama_base_url=ollama_base_url, 
                                                  ollama_model=ollama_model)  # type: ignore[attr-defined]
            tag_obj = tag_raw if isinstance(tag_raw, dict) else {"tags": list(tag_raw or []), "top": []}
            tags_path = ps.SUMMARY_DIR / (pdf_path.stem + ".tags.json")  # type: ignore[attr-defined]
            tags_path.write_text(json.dumps(tag_obj, ensure_ascii=False, indent=2), encoding="utf-8")
            _LOG.info("✅  Saved %d tag(s) for %s", len(tag_obj.get("tags", [])), pdf_path.stem)
        except Exception as exc:
            _LOG.exception("Failed to generate tags for %s: %s", pdf_path.stem, exc)

        _LOG.info("✅  Done – summary saved to %s", summary_path)
        return summary_path, pdf_url, paper_subject

    except Exception as exc:  # pylint: disable=broad-except
        _LOG.error("❌  %s – %s", url, exc)
        # _LOG.exception(exc)
        return None, None, None

# ---------------------------------------------------------------------------
# Local discovery helpers
# ---------------------------------------------------------------------------

def _collect_local_links() -> List[str]:
    """Discover local papers and return a list of direct PDF URLs.

    Preference order: markdown files (stems) → papers PDFs (stems). For each
    stem we construct a direct arXiv PDF URL, which will hit the local cache in
    download step when available.
    """
    links: List[str] = []
    try:
        # Prefer markdown directory if present
        md_dir: Path = ps.MD_DIR  # type: ignore[attr-defined]
        md_files = sorted(md_dir.glob("*.md")) if md_dir.exists() else []
        if md_files:
            for p in md_files:
                links.append(f"https://arxiv.org/pdf/{p.stem}.pdf")
            return links
    except Exception:
        pass

    try:
        pdf_dir: Path = ps.PDF_DIR  # type: ignore[attr-defined]
        pdf_files = sorted(pdf_dir.glob("*.pdf")) if pdf_dir.exists() else []
        for p in pdf_files:
            links.append(f"https://arxiv.org/pdf/{p.stem}.pdf")
    except Exception:
        pass

    return links


# ---------------------------------------------------------------------------
# Tags-only helper
# ---------------------------------------------------------------------------

def _tags_only_run() -> tuple[int, int]:
    """Generate tags for existing summaries only.

    Returns a tuple of (total_summaries, updated_count). Only summaries missing
    tags will be processed.
    """
    try:
        summary_dir: Path = ps.SUMMARY_DIR  # type: ignore[attr-defined]
    except Exception:
        _LOG.warning("Summary directory not available.")
        return 0, 0

    if not summary_dir.exists():
        _LOG.warning("Summary directory %s does not exist.", summary_dir)
        return 0, 0

    md_files = sorted(summary_dir.glob("*.md"))
    total = len(md_files)
    if total == 0:
        _LOG.info("No summaries found under %s", summary_dir)
        return 0, 0

    _LOG.info("🏷️  Tags-only mode – scanning %d summary file(s)…", total)
    updated = 0
    for md_path in md_files:
        try:
            tags_path = md_path.with_suffix("")
            tags_path = tags_path.with_name(tags_path.name + ".tags.json")
            if tags_path.exists():
                continue
            paper_id = md_path.stem
            _LOG.info("🏷️  Generating tags for %s…", paper_id)
            summary_text = md_path.read_text(encoding="utf-8", errors="ignore")
            tags = ps.generate_tags_from_summary(summary_text, provider=args.provider,
                                               ollama_base_url=args.ollama_base_url,
                                               ollama_model=args.ollama_model)  # type: ignore[attr-defined]
            tags_path.write_text(json.dumps({"tags": tags}, ensure_ascii=False, indent=2), encoding="utf-8")
            _LOG.info("✅  Saved %d tag(s) for %s", len(tags), paper_id)
            updated += 1
        except Exception as exc:  # pylint: disable=broad-except
            _LOG.exception("Failed to generate tags for %s: %s", md_path.name, exc)

    _LOG.info("🏷️  Tags-only complete – %d/%d updated", updated, total)
    return total, updated

# ---------------------------------------------------------------------------
# Aggregate summaries → single Markdown file
# ---------------------------------------------------------------------------

def _aggregate_summaries(paths: List[Path], out_file: Path, feed_url: str) -> None:
    """Concatenate individual summaries to *out_file* with a brief header."""
    header = (
        f"# Batch Summary – {feed_url}\n"
        f"_Generated: {_dt.datetime.now().isoformat(timespec='seconds')}_\n\n"
    )

    with out_file.open("w", encoding="utf-8") as fh:
        fh.write(header)
        for path in paths:
            fh.write(f"\n---\n\n## {path.stem}\n\n")
            fh.write(path.read_text(encoding="utf-8"))
            fh.write("\n")
    _LOG.info("📄  Aggregated summaries written to %s", out_file)

# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------

def _parse_args(argv: List[str] | None = None) -> argparse.Namespace:  # noqa: D401
    p = argparse.ArgumentParser(
        description="Fetch an RSS feed, process papers (extract text, summarize with LLM, generate tags), and aggregate results. Supports DeepSeek and Ollama LLM providers. Use --extract-only to skip LLM processing.",
    )
    p.add_argument("rss_url", nargs="?", default="", help="RSS feed URL (HuggingFace papers feed, ArXiv RSS, etc.)")
    p.add_argument("--api-key", dest="api_key", help="DeepSeek API key")
    p.add_argument("--provider", choices=["deepseek", "ollama"], default="deepseek",
                   help="LLM provider to use (default: deepseek)")
    p.add_argument("--ollama-base-url", default="http://localhost:11434",
                   help="Ollama service base URL (default: http://localhost:11434)")
    p.add_argument("--ollama-model", default="qwen3:8b",
                   help="Ollama model name (default: qwen3:8b)")
    p.add_argument("--proxy", help="Proxy URL to use for PDF downloads (if needed)")
    p.add_argument("--workers", type=int, default=os.cpu_count() or 4, help="Concurrent workers (default: CPU count)")
    p.add_argument("--output", type=Path, default=Path("output.md"), help="Aggregate markdown output file")
    p.add_argument("--output_rss_path", type=Path, default=Path("hugging-face-ai-papers-rss.xml"), help="RSS xml file output path.")
    p.add_argument("--rebuild", action="store_true", help="Whether to rebuild the rss xml file using all existing summaries.")
    p.add_argument("--local", action="store_true", help="Process local cached papers instead of fetching RSS.")
    p.add_argument("--tags-only", action="store_true", help="Only generate tags for existing summaries and exit.")
    p.add_argument("--extract-only", action="store_true", help="Only extract PDF text to markdown (no LLM calls, no summaries, no tags, no RSS generation).")
    p.add_argument("--debug", action="store_true", help="Verbose logging")
    p.add_argument("--input-char-limit", dest="max_input_char", default=100000, help="Max allowed number of input chars")
    return p.parse_args(argv)

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: List[str] | None = None) -> None:  # noqa: D401
    args = _parse_args(argv)
    _setup_logging(args.debug)

    _LOG.info("🚀  feed_paper_summarizer_service %s", __version__)

    # Proxy support – rebuild the session inside paper_summarizer if needed
    if args.proxy:
        ps.SESSION = ps.build_session(args.proxy)  # type: ignore[attr-defined]
        _LOG.warning("Using proxy %s", args.proxy)

    # Short-circuit: tags-only generation
    if args.tags_only:
        _tags_only_run()
        _LOG.info("✨  All done (tags-only).")
        # Clean up the log listener
        if _log_listener:
            _log_listener.stop()
            _log_listener = None
        return

    # ------------------------------------------------------------------
    # 1. Collect links
    # ------------------------------------------------------------------
    if args.local:
        _LOG.info("📦  Local mode enabled – discovering cached papers…")
        links = _collect_local_links()
        links = list(dict.fromkeys(links))
        if not links:
            _LOG.warning("No local papers discovered – nothing to do.")
            sys.exit(0)
        _LOG.info("Found %d local paper(s)", len(links))
    else:
        _LOG.info("🔗  Fetching RSS feed…")
        try:
            links = get_links_from_rss(args.rss_url, timeout=20.0)
        except Exception as exc:  # pylint: disable=broad-except
            _LOG.error("Failed to fetch RSS: %s", exc)
            sys.exit(1)

        links = list(dict.fromkeys(links))  # deduplicate while preserving order
        if not links:
            _LOG.warning("No links found – nothing to do.")
            sys.exit(0)
        _LOG.info("Found %d unique paper link(s)", len(links))

    # ------------------------------------------------------------------
    # 2. Parallel summarization
    # ------------------------------------------------------------------
    _LOG.info("🧵  Starting summarization with %d worker(s)…", args.workers)
    produced: List[Tuple[Optional[Path], Optional[str]]] = [(None, None)] * len(links)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _summarize_url,
                link,
                api_key=args.api_key,
                provider=args.provider,
                ollama_base_url=args.ollama_base_url,
                ollama_model=args.ollama_model,
                max_input_char=args.max_input_char,
                extract_only=args.extract_only,
            ): idx
            for idx, link in enumerate(links)
        }
        try:
            desc = "Text Extraction:" if args.extract_only else "Summaries:"
            for fut in tqdm(as_completed(futures), total=len(futures), desc=desc):
                try:
                    result = fut.result(timeout=30)  # 30 seconds timeout per task
                    produced[futures[fut]] = result
                except Exception as exc:
                    idx = futures[fut]
                    _LOG.error("Task failed for link %d (%s): %s", idx, links[idx] if idx < len(links) else "unknown", exc)
                    produced[idx] = (None, None, None)  # Mark as failed
        except KeyboardInterrupt:
            _LOG.warning("🛑  Processing interrupted by user. Cancelling remaining tasks...")
            # Cancel all pending futures
            for future in futures:
                if not future.done():
                    future.cancel()
            # Wait a bit for running tasks to finish
            import time
            time.sleep(2)
            raise  # Re-raise to be caught by main handler

    successes = [p for p in produced if p[0]]
    success_summaries_paths = [s[0] for s in successes]
    if args.extract_only:
        _LOG.info("✔️  %d/%d papers extracted to markdown successfully", len(successes), len(links))
    else:
        _LOG.info("✔️  %d/%d summaries generated successfully", len(successes), len(links))
    if not successes:
        if args.extract_only:
            _LOG.error("No papers extracted successfully – aborting.")
        else:
            _LOG.error("No summaries produced – aborting.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Aggregate → single file (skip in extract_only mode)
    # ------------------------------------------------------------------
    if not args.extract_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        _aggregate_summaries(success_summaries_paths, args.output, args.rss_url)

    # ------------------------------------------------------------------
    # 4. Generate rss xml file (skip in extract_only mode)
    # ------------------------------------------------------------------
    if not args.extract_only:
        RSS_FILE_PATH = args.output_rss_path
        # Step 1: Read existing RSS file if it exists
        existing_entries = []
        if not args.rebuild:
            if os.path.exists(RSS_FILE_PATH):
                tree = ET.parse(RSS_FILE_PATH)
                root = tree.getroot()

                # Extract existing RSS entries (items)
                for item in root.findall(".//item"):
                    paper_url = item.find("link").text
                    existing_entries.append(paper_url)

        # Step 2: Initialize a FeedGenerator for the new RSS feed
        fg = FeedGenerator()

        # Set the feed details (if not already set)
        fg.title('Research Paper Summaries')
        fg.link(href='https://yourwebsite.com')  # Your site or feed URL
        fg.description('Summaries of research papers')

        if args.rebuild:
            _LOG.info("Remove current rss file and rebuild using local summaries...")
            if os.path.exists(args.output_rss_path):
                os.remove(args.output_rss_path)
            papers = glob("markdown/*.md")
            for p in papers:
                with open(p, 'r', encoding='utf-8') as f:
                    text = f.read()
                    paper_subject = extract_first_header(text)
                    pdf_url = "https://arxiv.org/pdf/" + p.split(os.path.sep)[-1].replace('.md', ".pdf")
                    summary_path = Path(p.replace('markdown/', 'summary/'))
                    if summary_path.exists():
                        successes.append((summary_path, pdf_url, paper_subject))

        # Step 3: Process and add new items to the RSS feed
        new_items = []
        for path, paper_url, *rest in successes:
            # Handle inconsistent data structure - some items might be missing paper_subject
            paper_subject = rest[0] if rest else "Unknown Title"

            # Validate that the summary file exists before trying to read it
            if not path.exists():
                _LOG.warning(f"Summary file {path} does not exist, skipping RSS entry")
                continue

            try:
                paper_summary_markdown_content = path.read_text(encoding="utf-8")
                paper_summary_html = markdown.markdown(paper_summary_markdown_content)

                # Check if this paper has already been added by checking the URL
                if paper_url not in existing_entries:
                    # Add a new entry to the RSS feed
                    entry = fg.add_entry()
                    entry.title(f"{paper_subject}")
                    entry.link(href=paper_url)
                    entry.description(paper_summary_html)
                    new_items.append(entry)
                else:
                    _LOG.debug(f"Paper {paper_url} already exists in RSS feed, skipping")
            except Exception as e:
                _LOG.error(f"Failed to process {path} for RSS: {e}")
                continue

        # Step 4: Recreate existing entries from the preserved data
        if not args.rebuild and existing_entries:
            _LOG.info(f"Found {len(existing_entries)} existing RSS entries, recreating them...")
            # Read the existing RSS file and recreate entries
            tree = ET.parse(RSS_FILE_PATH)
            root = tree.getroot()

            for item in root.findall(".//item"):
                title_elem = item.find("title")
                link_elem = item.find("link")
                desc_elem = item.find("description")

                if title_elem is not None and link_elem is not None and desc_elem is not None:
                    entry = fg.add_entry()
                    entry.title(title_elem.text or "Unknown Title")
                    entry.link(href=link_elem.text or "")
                    entry.description(desc_elem.text or "")

        # Step 5: Keep only the latest 30 items in the RSS feed
        current_entries = fg.entry()
        if len(current_entries) > 30:
            # Note: FeedGenerator doesn't support direct truncation
            # We'll need to create a new FeedGenerator with only the first 30 entries
            _LOG.info(f"Truncating RSS feed to 30 items (was {len(current_entries)} items)")

            # Create a new FeedGenerator with truncated entries
            fg_truncated = FeedGenerator()
            fg_truncated.title('Research Paper Summaries')
            fg_truncated.link(href='https://yourwebsite.com')
            fg_truncated.description('Summaries of research papers')

            # Add only the first 30 entries
            for entry in current_entries[:30]:
                new_entry = fg_truncated.add_entry()
                new_entry.title(entry.title())
                new_entry.link(href=entry.link()[0]['href'])
                new_entry.description(entry.description())

            fg = fg_truncated

        # Step 6: Write the updated feed back to the RSS file
        with open(RSS_FILE_PATH, 'w', encoding="utf-8") as rss_file:
            rss_file.write(fg.rss_str(pretty=True).decode('utf-8'))

        total_entries = len(fg.entry())
        _LOG.info(f"📢 RSS feed updated: {len(new_items)} new items added, {total_entries} total items in feed")

    _LOG.info("✨  All done!")
    
    # Clean up the log listener
    if _log_listener:
        _log_listener.stop()
        _log_listener = None


if __name__ == "__main__":  # pragma: no cover
    try:
        main()
    except KeyboardInterrupt:
        _LOG.info("🛑  Process interrupted by user. Cleaning up...")
        # Clean up the log listener
        if _log_listener:
            _log_listener.stop()
            _log_listener = None
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        _LOG.error("💥  Fatal error: %s", e)
        # Clean up the log listener
        if _log_listener:
            _log_listener.stop()
            _log_listener = None
        sys.exit(1)

# Example usage:
# Regular mode with DeepSeek LLM (default):
#   uv run python feed_paper_summarizer_service.py https://papers.takara.ai/api/feed --workers 2
#
# Regular mode with Ollama LLM:
#   uv run python feed_paper_summarizer_service.py https://papers.takara.ai/api/feed --provider ollama --ollama-base-url http://192.168.31.192:11434 --ollama-model qwen3:8b --workers 2
#
# Extract-only mode (no LLM, just text extraction):
#   uv run python feed_paper_summarizer_service.py https://papers.takara.ai/api/feed --extract-only --workers 4
#
# Tags-only mode (only generate tags for existing summaries):
#   uv run python feed_paper_summarizer_service.py --tags-only --provider ollama --ollama-base-url http://192.168.31.192:11434 --ollama-model qwen3:8b

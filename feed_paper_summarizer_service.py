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
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple
import re

from tqdm import tqdm
import markdown
from feedgen.feed import FeedGenerator

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

# ---------------------------------------------------------------------------
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
) -> Tuple[Optional[Path], Optional[str]]:
    """Run the full summarization pipeline for *url*.

    Returns the Path to the generated summary markdown and the download url for the paper, 
    or *None* on failure. Only very high‑level logs are emitted here – fine‑grained steps are already
    logged inside ``paper_summarizer``.
    """
    _LOG.info("📝  Summarizing %s", url)

    try:
        pdf_url = ps.resolve_pdf_url(url)  # type: ignore[attr-defined]
        pdf_path = ps.download_pdf(pdf_url)  # type: ignore[attr-defined]
        md_path = ps.extract_markdown(pdf_path)  # type: ignore[attr-defined]

        text = md_path.read_text(encoding="utf-8")
        paper_subject = extract_first_header(text)
        chunks = ps.chunk_text(text)  # type: ignore[attr-defined]

        f_name = paper_subject + ('_' if paper_subject else '') + pdf_path.stem + ".md"
        summary_path = ps.SUMMARY_DIR / f_name  # type: ignore[attr-defined]
        if summary_path.exists():
            _LOG.warning(f"{summary_path} existed")
            return summary_path, pdf_url
        chunks_summary_out_path = ps.CHUNKS_SUMMARY_DIR / f_name
        summary, chunks_summary = ps.progressive_summary(  # type: ignore[attr-defined]
            chunks, summary_path=summary_path, chunk_summary_path=chunks_summary_out_path, api_key=api_key
        )

        chunks_summary_out_path.write_text(chunks_summary, encoding="utf-8")
        summary_path.write_text(summary, encoding="utf-8")

        _LOG.info("✅  Done – summary saved to %s", summary_path)
        return summary_path, pdf_url

    except Exception as exc:  # pylint: disable=broad-except
        _LOG.error("❌  %s – %s", url, exc)
        _LOG.exception(exc)
        return None, None

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
        description="Fetch an RSS feed, summarize each linked paper in parallel, and aggregate the results.",
    )
    p.add_argument("rss_url", help="RSS feed URL (HuggingFace papers feed, ArXiv RSS, etc.)")
    p.add_argument("--api-key", dest="api_key", help="DeepSeek / OpenAI API key")
    p.add_argument("--proxy", help="Proxy URL to use for PDF downloads (if needed)")
    p.add_argument("--workers", type=int, default=os.cpu_count() or 4, help="Concurrent workers (default: CPU count)")
    p.add_argument("--output", type=Path, default=Path("output.md"), help="Aggregate markdown output file")
    p.add_argument("--rss_path", type=Path, default=Path("hugging-face-ai-papers-rss.xml"), help="RSS xml file path")
    p.add_argument("--debug", action="store_true", help="Verbose logging")
    return p.parse_args(argv)

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: List[str] | None = None) -> None:  # noqa: D401
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
    )

    _LOG.info("🚀  feed_paper_summarizer_service %s", __version__)

    # Proxy support – rebuild the session inside paper_summarizer if needed
    if args.proxy:
        ps.SESSION = ps.build_session(args.proxy)  # type: ignore[attr-defined]
        _LOG.debug("Using proxy %s", args.proxy)

    # ------------------------------------------------------------------
    # 1. Collect links from RSS
    # ------------------------------------------------------------------
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
            pool.submit(_summarize_url, link, api_key=args.api_key): idx
            for idx, link in enumerate(links)
        }
        for fut in tqdm(as_completed(futures), total=len(futures), desc="Summaries:"):
            produced[futures[fut]] = fut.result()

    successes = [p for p in produced if p[0]]
    success_summaries_paths = [s[0] for s in successes]
    _LOG.info("✔️  %d/%d summaries generated successfully", len(successes), len(links))
    if not successes:
        _LOG.error("No summaries produced – aborting.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Aggregate → single file
    # ------------------------------------------------------------------
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _aggregate_summaries(success_summaries_paths, args.output, args.rss_url)

    # ------------------------------------------------------------------
    # 4. Generate rss xml file
    # ------------------------------------------------------------------
    RSS_FILE_PATH = args.rss_path
    # Step 1: Read existing RSS file if it exists
    existing_feed = None
    existing_items = []
    if os.path.exists(RSS_FILE_PATH):
        existing_feed = FeedGenerator()
        existing_feed.load(RSS_FILE_PATH)
        existing_items = existing_feed.entries  # Get existing entries

    # Step 2: Initialize a FeedGenerator for the new RSS feed
    fg = FeedGenerator()

    # Set the feed details (if not already set)
    fg.title('Research Paper Summaries')
    fg.link(href='https://yourwebsite.com')  # Your site or feed URL
    fg.description('Summaries of research papers')

    # Step 3: Process and add new items to the RSS feed
    new_items = []
    for path, paper_url in successes:
        paper_summary_markdown_content = path.read_text(encoding="utf-8")
        paper_summary_html = markdown.markdown(paper_summary_markdown_content)

        # Check if this paper has already been added by checking the URL
        item_exists = any(item.link == paper_url for item in existing_items)
        
        if not item_exists:
            # Add a new entry to the RSS feed
            entry = fg.add_entry()
            entry.title(f"Summary of paper at {paper_url}")  # Set a meaningful title for the entry
            entry.link(href=paper_url)  # Link to the paper's URL
            entry.description(paper_summary_html)  # HTML description of the paper
            new_items.append(entry)

    # Step 4: Combine new items with existing ones
    all_entries = existing_items + new_items  # Combine old and new entries

    # Step 5: Keep only the latest 20 items in the RSS feed
    fg.entries = all_entries[:20]  # Slice the list to keep only the latest 20

    # Step 6: Write the updated feed back to the RSS file
    with open(RSS_FILE_PATH, 'w', encoding="utf-8") as rss_file:
        rss_file.write(fg.rss_str(pretty=True).decode('utf-8'))

    _LOG.info("📢 RSS feed updated successfully.")
        

    _LOG.info("✨  All done!")


if __name__ == "__main__":  # pragma: no cover
    main()

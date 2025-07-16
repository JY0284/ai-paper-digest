"""
collect_hf_paper_links_from_rss.py

Fetch an RSS feed from a URL and extract all <item><link> values.
"""

import argparse
import logging
import sys
from typing import List

import requests
import xml.etree.ElementTree as ET

__version__ = "0.1.0"


def fetch_rss(url: str, timeout) -> str:
    """
    Download the RSS feed XML from the given URL.
    
    :param url: RSS feed URL
    :param timeout: Request timeout in seconds
    :return: XML content as text
    :raises: requests.exceptions.RequestException on network errors
    """
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse_links(xml_content: str) -> List[str]:
    """
    Parse RSS XML content and extract all <item><link> values.
    
    :param xml_content: RSS feed as string
    :return: List of URLs found in <item><link>
    """
    root = ET.fromstring(xml_content)
    # RSS 2.0 standard: items are under channel/item
    links = []
    for item in root.findall("./channel/item"):
        link_el = item.find("link")
        if link_el is not None and link_el.text:
            links.append(link_el.text.strip())
    return links


def get_links_from_rss(url: str, timeout: float=10.0) -> List[str]:
    """
    Convenience wrapper: fetch + parse.
    
    :param url: RSS feed URL
    :return: List of links
    """
    xml = fetch_rss(url, timeout)
    return parse_links(xml)


def main():
    parser = argparse.ArgumentParser(
        description="Collect all <item><link> URLs from an RSS feed."
    )
    parser.add_argument(
        "url",
        metavar="RSS_URL",
        help="The URL of the RSS feed to parse",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging"
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    try:
        links = get_links_from_rss(args.url)
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch RSS feed: {e}")
        sys.exit(1)
    except ET.ParseError as e:
        logging.error(f"Failed to parse XML: {e}")
        sys.exit(1)

    if not links:
        logging.warning("No <item><link> entries found in the feed.")
        sys.exit(0)

    # Print one link per line for easy consumption by other tools
    for link in links:
        print(link)


if __name__ == "__main__":
    main()

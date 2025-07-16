import os
from datetime import datetime

# Define the directory where debug logs will be stored
DEBUG_DIR = os.path.join(os.path.dirname(__file__), "debug_logs")
os.makedirs(DEBUG_DIR, exist_ok=True)

def generate_debug_file(tag: str, content: str):
    """
    Write debug content with a tag and current datetime (human readable format)
    to a file in the inter/utils.py directory (./debug_logs/).
    
    Args:
        tag (str): Tag or identifier for the debug entry (used in filename and entry).
        content (str): Content to log.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filename = os.path.join(DEBUG_DIR, f"{tag}_{timestamp}.md")
    
    with open(filename, "a", encoding="utf-8") as f:
        f.write(content)
        f.write('\n')


def get_debug_log_path() -> str:
    return DEBUG_DIR
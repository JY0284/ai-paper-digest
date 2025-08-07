import os
import json
from pathlib import Path
from datetime import datetime, date

from flask import (
    Flask,
    render_template_string,
    abort,
    send_from_directory,
    request,
    make_response,
    jsonify,
    redirect,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
import markdown

app = Flask(__name__)
app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_proto = 1,     # trust 1 hop for X-Forwarded-Proto
        x_host  = 1,     # trust 1 hop for X-Forwarded-Host
        x_prefix= 1)     # <-- pay attention to X-Forwarded-Prefix

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

SUMMARY_DIR = Path(__file__).parent / "summary"  # folder with <arxiv_id>.md
USER_DATA_DIR = Path(__file__).parent / "user_data"  # persisted read-status
SUMMARY_DIR.mkdir(exist_ok=True)
USER_DATA_DIR.mkdir(exist_ok=True)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def render_markdown(md_text: str) -> str:
    """Convert Markdown → HTML (GitHub-flavoured-ish)."""
    return markdown.markdown(
        md_text,
        extensions=[
            "fenced_code",
            "tables",
            "codehilite",
            "toc",
            "attr_list",
        ],
    )


def get_entries():
    """Return list of summary files sorted by modified-time (desc)."""
    entries: list[dict] = []

    for path in SUMMARY_DIR.glob("*.md"):
        stat = path.stat()
        updated = datetime.fromtimestamp(stat.st_mtime)

        # ⬇️  Read the *whole* file instead of the first 40 lines
        md_text = path.read_text(encoding="utf-8", errors="ignore")
        preview_html = render_markdown(md_text)

        entries.append(
            {
                "id": path.stem,
                "updated": updated,
                "preview_html": preview_html,
            }
        )

    entries.sort(key=lambda e: e["updated"], reverse=True)
    return entries



# ------------------------- user-state helpers ---------------------------------

def _user_file(uid: str) -> Path:
    return USER_DATA_DIR / f"{uid}.json"


def load_read_set(uid: str) -> set[str]:
    try:
        data = json.loads(_user_file(uid).read_text())
        return set(data.get("read", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_read_set(uid: str, read_set: set[str]):
    _user_file(uid).write_text(json.dumps({"read": sorted(read_set)}), encoding="utf-8")

# -----------------------------------------------------------------------------
# Templates (plain strings — no Python f-strings)                               
# -----------------------------------------------------------------------------

BASE_CSS = open('ui/base.css', 'r').read()
INDEX_TEMPLATE = open('ui/index.html', 'r').read()
DETAIL_TEMPLATE = open('ui/detail.html', 'r').read()

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    uid = request.cookies.get("uid")
    entries = get_entries()
    unread_count = None
    read_total = None
    read_today = None
    if uid:
        read_set = load_read_set(uid)
        unread_count = len([e for e in entries if e["id"] not in read_set])
        entries = [e for e in entries if e["id"] not in read_set]
        read_total = len(read_set)
        # Count how many read today
        today = date.today()
        read_today = 0
        for rid in read_set:
            summary_path = SUMMARY_DIR / f"{rid}.md"
            if summary_path.exists():
                mtime = datetime.fromtimestamp(summary_path.stat().st_mtime)
                if mtime.date() == today:
                    read_today += 1
    resp = make_response(render_template_string(INDEX_TEMPLATE, entries=entries, uid=uid, css=BASE_CSS, unread_count=unread_count, read_total=read_total, read_today=read_today))
    return resp


@app.route("/set_user", methods=["POST"])
def set_user():
    uid = request.form.get("uid", "").strip()
    if not uid:
        return redirect(url_for("index"))
    resp = make_response(redirect(url_for("index")))
    resp.set_cookie("uid", uid, max_age=60 * 60 * 24 * 365 * 3)  # 3-year cookie
    return resp


@app.route("/mark_read/<arxiv_id>", methods=["POST"])
def mark_read(arxiv_id):
    uid = request.cookies.get("uid")
    if not uid:
        return jsonify({"error": "no-uid"}), 400
    read_set = load_read_set(uid)
    read_set.add(arxiv_id)
    save_read_set(uid, read_set)
    return jsonify({"status": "ok"})


@app.route("/unmark_read/<arxiv_id>", methods=["POST"])
def unmark_read(arxiv_id):
    uid = request.cookies.get("uid")
    if not uid:
        return jsonify({"error": "no-uid"}), 400
    read_set = load_read_set(uid)
    read_set.discard(arxiv_id)
    save_read_set(uid, read_set)
    return jsonify({"status": "ok"})


@app.route("/reset", methods=["POST"])
def reset_read():
    uid = request.cookies.get("uid")
    if not uid:
        return jsonify({"error": "no-uid"}), 400
    try:
        _user_file(uid).unlink(missing_ok=True)
    except Exception:
        pass
    return jsonify({"status": "reset"})


@app.route("/summary/<arxiv_id>")
def view_summary(arxiv_id):
    md_path = SUMMARY_DIR / f"{arxiv_id}.md"
    if not md_path.exists():
        abort(404)
    md_text = md_path.read_text(encoding="utf-8", errors="ignore")
    html_content = render_markdown(md_text)
    return render_template_string(DETAIL_TEMPLATE, content=html_content, arxiv_id=arxiv_id, css=BASE_CSS)


@app.route("/raw/<arxiv_id>.md")
def raw_markdown(arxiv_id):
    md_path = SUMMARY_DIR / f"{arxiv_id}.md"
    if not md_path.exists():
        abort(404)
    return send_from_directory(md_path.parent, md_path.name, mimetype="text/markdown")


@app.route("/read")
def read_papers():
    uid = request.cookies.get("uid")
    if not uid:
        return redirect(url_for("index"))
    read_set = load_read_set(uid)
    entries = get_entries()
    read_entries = [e for e in entries if e["id"] in read_set]
    return render_template_string(INDEX_TEMPLATE, entries=read_entries, uid=uid, css=BASE_CSS, unread_count=None, read_total=None, read_today=None, show_read=True)

# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"✅ Serving summaries from {SUMMARY_DIR.resolve()}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 22581)), debug=True)
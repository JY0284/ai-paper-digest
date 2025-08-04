import os
import json
from pathlib import Path
from datetime import datetime

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
import markdown

app = Flask(__name__)

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
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            snippet_lines = [fh.readline() for _ in range(40)]
        snippet_md = "".join(snippet_lines)
        preview_html = render_markdown(snippet_md)
        entries.append({"id": path.stem, "updated": updated, "preview_html": preview_html})

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

BASE_CSS = """
body {font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,Cantarell,'Open Sans','Helvetica Neue',sans-serif;margin:0;padding:0;background:#f5f7fa;}
header {background:#24292f;color:#fff;padding:1rem 2rem;display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;}
header h1{margin:0;font-size:1.25rem;}
header a{color:#fff;text-decoration:none;font-weight:600;}
form#user-form input{padding:0.25rem 0.5rem;border-radius:4px;border:none;margin-right:0.5rem;}
form#user-form button{padding:0.25rem 0.75rem;border:none;border-radius:4px;cursor:pointer;}
main{max-width:980px;margin:auto;padding:2rem 1rem 4rem;}
article{background:#fff;border-radius:1rem;box-shadow:0 4px 12px rgba(0,0,0,0.06);padding:2rem 2.5rem;margin-bottom:2rem;position:relative;}
article h2{margin:0 0 0.5rem 0;font-size:1.35rem;}
.preview-html{transition:max-height 0.2s ease-in-out;overflow:hidden;}
.preview-html.collapsed{max-height:12rem;}
.toggle-link{cursor:pointer;font-size:0.9rem;user-select:none;}
.card-actions{margin-top:0.75rem;font-size:0.9rem;color:#666;}
.card-actions a{margin-right:0.75rem;cursor:pointer;}
.muted{color:#666;font-size:0.85rem;}
.markdown-body{line-height:1.65;}
pre{overflow:auto;background:#f6f8fa;padding:1rem;border-radius:6px;}
code{background:#f6f8fa;padding:0.2rem 0.4rem;border-radius:4px;font-size:87%;}
"""

INDEX_TEMPLATE = """<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <title>ArXiv Paper Summaries</title>
  <meta name='viewport' content='width=device-width,initial-scale=1'>
  <style>{{ css }}</style>
</head>
<body>
<header>
  <h1><a href='{{ url_for("index") }}'>📚 ArXiv Paper Summaries</a></h1>
  {% if uid %}
    <div style='display:flex;align-items:center;gap:0.5rem;'>
      <span style='font-size:0.9rem;'>User: <strong>{{ uid }}</strong></span>
      <button id='reset-btn' style='padding:0.25rem 0.6rem;border:none;border-radius:4px;cursor:pointer;'>Reset</button>
    </div>
  {% else %}
    <form id='user-form' method='POST' action='{{ url_for("set_user") }}'>
      <input name='uid' placeholder='Enter ID/username' required>
      <button type='submit'>Go</button>
    </form>
  {% endif %}
</header>
<main>
  {% for e in entries %}
    <article data-id='{{ e.id }}'>
      <h2><a href='{{ url_for("view_summary", arxiv_id=e.id) }}'>{{ e.id }}</a></h2>
      <div class='preview-html collapsed'>{{ e.preview_html | safe }}</div>
      <div class='card-actions'>
        <a class='toggle-link'>Show more</a>
        {% if uid %}<a class='mark-read-link'>Mark as read</a>{% endif %}
        <a target='_blank' href='https://arxiv.org/pdf/{{ e.id }}.pdf'>Open PDF</a>
      </div>
      <p class='muted'>Updated: {{ e.updated.strftime('%Y-%m-%d %H:%M') }}</p>
    </article>
  {% else %}
    <p>No unread summaries found.</p>
  {% endfor %}
</main>
<script>
// Expand / collapse preview blocks
function togglePreview(link){
  const art = link.closest('article');
  const prev = art.querySelector('.preview-html');
  prev.classList.toggle('collapsed');
  link.textContent = prev.classList.contains('collapsed') ? 'Show more' : 'Show less';
}

// Mark summary as read and hide card
function markRead(link){
  const art = link.closest('article');
  const id = art.getAttribute('data-id');
  fetch(`/mark_read/${id}`, {method:'POST'}).then(r=>{
    if(r.ok){ art.remove(); }
  });
}

// Reset read status
function resetAll(){
  fetch('/reset', {method:'POST'}).then(r=>{ if(r.ok) location.reload(); });
}

document.addEventListener('click', ev=>{
  if(ev.target.matches('.toggle-link')){ ev.preventDefault(); togglePreview(ev.target); }
  if(ev.target.matches('.mark-read-link')){ ev.preventDefault(); markRead(ev.target); }
  if(ev.target.id==='reset-btn'){ ev.preventDefault(); resetAll(); }
});
</script>
</body>
</html>"""

DETAIL_TEMPLATE = """<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width,initial-scale=1'>
  <title>{{ arxiv_id }} – Summary</title>
  <style>{{ css }}</style>
</head>
<body>
<header>
  <h1><a href='{{ url_for("index") }}'>← Back to list</a></h1>
</header>
<main>
  <article class='markdown-body'>
    {{ content | safe }}
  </article>
  <p style='text-align:center;margin-top:2rem;'>
    <a target='_blank' href='https://arxiv.org/pdf/{{ arxiv_id }}.pdf'>📄 Open original paper PDF</a>
  </p>
</main>
</body>
</html>"""

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    uid = request.cookies.get("uid")
    entries = get_entries()
    if uid:
        read_set = load_read_set(uid)
        entries = [e for e in entries if e["id"] not in read_set]
    resp = make_response(render_template_string(INDEX_TEMPLATE, entries=entries, uid=uid, css=BASE_CSS))
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

# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"✅ Serving summaries from {SUMMARY_DIR.resolve()}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 12580)), debug=True)
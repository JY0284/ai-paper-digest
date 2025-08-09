import os
import json
from pathlib import Path
from datetime import datetime, date, timezone, timedelta

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
    Response,
)
from werkzeug.middleware.proxy_fix import ProxyFix
import markdown
import math

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


_ENTRIES_CACHE: dict = {
    "meta": None,           # list of dicts without preview_html
    "count": 0,
    "latest_mtime": 0.0,    # max mtime among md/tag files
}


def _scan_entries_meta() -> list[dict]:
    """Scan summary directory and build metadata for all entries (no HTML).

    Returns a list of dicts with keys: id, updated, tags, top_tags, detail_tags.
    This function also maintains a lightweight cache to avoid re-reading tag
    files on every request when nothing changed.
    """
    md_files = list(SUMMARY_DIR.glob("*.md"))
    count = len(md_files)
    # compute latest mtime considering the md file and its .tags.json sibling
    latest_mtime = 0.0
    for p in md_files:
        try:
            latest_mtime = max(latest_mtime, p.stat().st_mtime)
            t = p.with_suffix("")
            t = t.with_name(t.name + ".tags.json")
            if t.exists():
                latest_mtime = max(latest_mtime, t.stat().st_mtime)
        except Exception:
            continue

    if (
        _ENTRIES_CACHE.get("meta") is not None
        and _ENTRIES_CACHE.get("count") == count
        and float(_ENTRIES_CACHE.get("latest_mtime") or 0.0) >= float(latest_mtime)
    ):
        return list(_ENTRIES_CACHE["meta"])  # type: ignore[index]

    entries_meta: list[dict] = []
    for path in md_files:
        try:
            stat = path.stat()
            updated = datetime.fromtimestamp(stat.st_mtime)

            # load tags saved alongside the summary (no markdown rendering here)
            tags: list[str] = []
            top_tags: list[str] = []
            detail_tags: list[str] = []
            tags_file = path.with_suffix("")
            tags_file = tags_file.with_name(tags_file.name + ".tags.json")
            try:
                if tags_file.exists():
                    data = json.loads(tags_file.read_text(encoding="utf-8"))
                    # support legacy [..], flat {"top": [...], "tags": [...]},
                    # and nested {"tags": {"top": [...], "tags": [...]}}
                    if isinstance(data, list):
                        detail_tags = [str(t).strip().lower() for t in data if str(t).strip()]
                    elif isinstance(data, dict):
                        container = data
                        if isinstance(data.get("tags"), dict):
                            container = data.get("tags") or {}
                        if isinstance(container.get("top"), list):
                            top_tags = [str(t).strip().lower() for t in container.get("top") if str(t).strip()]
                        if isinstance(container.get("tags"), list):
                            detail_tags = [str(t).strip().lower() for t in container.get("tags") if str(t).strip()]
                    tags = (top_tags or []) + (detail_tags or [])
            except Exception:
                tags = []

            entries_meta.append(
                {
                    "id": path.stem,
                    "updated": updated,
                    "tags": tags,
                    "top_tags": top_tags,
                    "detail_tags": detail_tags,
                }
            )
        except Exception:
            continue

    entries_meta.sort(key=lambda e: e["updated"], reverse=True)
    _ENTRIES_CACHE["meta"] = list(entries_meta)
    _ENTRIES_CACHE["count"] = count
    _ENTRIES_CACHE["latest_mtime"] = latest_mtime
    return entries_meta


def _render_page_entries(entries_meta: list[dict]) -> list[dict]:
    """Given a slice of entries meta, materialize preview_html for each."""
    rendered: list[dict] = []
    for meta in entries_meta:
        try:
            md_path = SUMMARY_DIR / f"{meta['id']}.md"
            md_text = md_path.read_text(encoding="utf-8", errors="ignore")
            preview_html = render_markdown(md_text)
        except Exception:
            preview_html = ""
        item = dict(meta)
        item["preview_html"] = preview_html
        rendered.append(item)
    return rendered



# ------------------------- user-state helpers ---------------------------------

def _user_file(uid: str) -> Path:
    return USER_DATA_DIR / f"{uid}.json"


def load_user_data(uid: str) -> dict:
    """Load full user data structure with backward compatibility.

    Shape:
    {
      "read": {arxiv_id: "YYYY-MM-DD" | null, ...},
      "events": [ {"ts": ISO8601, "type": str, "arxiv_id": str|None, "meta": dict|None, "path": str|None, "ua": str|None}, ... ]
    }
    """
    try:
        data = json.loads(_user_file(uid).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    # migrate legacy list-based read
    raw_read = data.get("read", {})
    if isinstance(raw_read, list):
        read_map = {str(rid): None for rid in raw_read}
    elif isinstance(raw_read, dict):
        read_map = {str(k): v for k, v in raw_read.items()}
    else:
        read_map = {}

    events = data.get("events")
    if not isinstance(events, list):
        events = []

    return {"read": read_map, "events": events}


def load_read_map(uid: str) -> dict[str, str | None]:
    data = load_user_data(uid)
    return data.get("read", {})


def save_user_data(uid: str, data: dict) -> None:
    _user_file(uid).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def save_read_map(uid: str, read_map: dict[str, str | None]):
    """Persist read map, preserving other fields (like events)."""
    data = load_user_data(uid)
    data["read"] = read_map
    save_user_data(uid, data)


def append_event(uid: str, event_type: str, arxiv_id: str | None = None, meta: dict | None = None, ts: str | None = None):
    """Append a single analytics event for the user.

    If ts is provided (ISO 8601, preferably with timezone offset), it will be
    used. Otherwise, we store the server local timezone timestamp with offset.
    """
    data = load_user_data(uid)
    evt = {
        "ts": ts or datetime.now().astimezone().isoformat(timespec="seconds"),
        "type": event_type,
        "arxiv_id": arxiv_id,
        "meta": meta or {},
        "path": request.path if request else None,
        "ua": request.headers.get("User-Agent") if request else None,
    }
    data.setdefault("events", []).append(evt)
    save_user_data(uid, data)

# -----------------------------------------------------------------------------
# Templates (plain strings — no Python f-strings)                               
# -----------------------------------------------------------------------------

BASE_CSS = open(os.path.join('ui', 'base.css'), 'r', encoding='utf-8').read()
INDEX_TEMPLATE = open(os.path.join('ui', 'index.html'), 'r', encoding='utf-8').read()
DETAIL_TEMPLATE = open(os.path.join('ui', 'detail.html'), 'r', encoding='utf-8').read()

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    uid = request.cookies.get("uid")
    entries_meta = _scan_entries_meta()
    # tag filtering (from query string)
    active_tag = (request.args.get("tag") or "").strip().lower() or None
    tag_query = (request.args.get("q") or "").strip().lower()
    # support multiple top filters: ?top=llm&top=cv
    active_tops = [t.strip().lower() for t in request.args.getlist("top") if t.strip()]
    unread_count = None
    read_total = None
    read_today = None
    if uid:
        read_map = load_read_map(uid)
        read_ids = set(read_map.keys())
        unread_count = len([e for e in entries_meta if e["id"] not in read_ids])
        entries_meta = [e for e in entries_meta if e["id"] not in read_ids]
        read_total = len(read_ids)
        # Count how many read today, based on stored per-paper read date/time (YYYY-MM-DD[THH:MM:SS])
        today_iso = date.today().isoformat()
        read_today = 0
        for d in read_map.values():
            if not d:
                continue
            try:
                # match date prefix for both date-only and datetime strings
                if str(d).split('T', 1)[0] == today_iso:
                    read_today += 1
            except Exception:
                continue
    # apply tag-based filters if present
    if active_tag:
        entries_meta = [e for e in entries_meta if active_tag in (e.get("detail_tags") or []) or active_tag in (e.get("top_tags") or [])]
    if tag_query:
        def matches_query(tags: list[str] | None, query: str) -> bool:
            if not tags:
                return False
            for t in tags:
                if query in t:
                    return True
            return False
        entries_meta = [e for e in entries_meta if matches_query(e.get("detail_tags"), tag_query) or matches_query(e.get("top_tags"), tag_query)]
    if active_tops:
        entries_meta = [e for e in entries_meta if any(t in (e.get("top_tags") or []) for t in active_tops)]

    # compute tag cloud from filtered entries only (meta only, no HTML work)
    tag_counts: dict[str, int] = {}
    top_counts: dict[str, int] = {}
    for e in entries_meta:
        for t in e.get("detail_tags", []) or []:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        for t in e.get("top_tags", []) or []:
            top_counts[t] = top_counts.get(t, 0) + 1

    # sort tags by frequency then name
    tag_cloud = sorted(
        ({"name": k, "count": v} for k, v in tag_counts.items()),
        key=lambda item: (-item["count"], item["name"]),
    )
    top_cloud = sorted(
        ({"name": k, "count": v} for k, v in top_counts.items()),
        key=lambda item: (-item["count"], item["name"]),
    )

    # when searching, show only related detailed tags in the filter bar
    if tag_query:
        tag_cloud = [t for t in tag_cloud if tag_query in t["name"]]

    # pagination
    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 10))
    except Exception:
        per_page = 10
    per_page = max(1, min(per_page, 30))
    total_items = len(entries_meta)
    total_pages = max(1, math.ceil(total_items / per_page))
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_entries = entries_meta[start:end]

    # materialize preview HTML only for current page
    entries = _render_page_entries(page_entries)

    resp = make_response(
        render_template_string(
            INDEX_TEMPLATE,
            entries=entries,
            uid=uid,
            unread_count=unread_count,
            read_total=read_total,
            read_today=read_today,
            tag_cloud=tag_cloud,
            active_tag=active_tag,
            top_cloud=top_cloud,
            active_tops=active_tops,
            tag_query=tag_query,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            total_items=total_items,
        )
    )
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
    read_map = load_read_map(uid)
    # store local date-time with timezone offset for more precise analytics
    read_map[str(arxiv_id)] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_read_map(uid, read_map)
    return jsonify({"status": "ok"})


@app.route("/unmark_read/<arxiv_id>", methods=["POST"])
def unmark_read(arxiv_id):
    uid = request.cookies.get("uid")
    if not uid:
        return jsonify({"error": "no-uid"}), 400
    read_map = load_read_map(uid)
    read_map.pop(str(arxiv_id), None)
    save_read_map(uid, read_map)
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
    uid = request.cookies.get("uid")
    html_content = render_markdown(md_text)
    # load tags for this paper
    tags: list[str] = []
    tpath = md_path.with_suffix("")
    tpath = tpath.with_name(tpath.name + ".tags.json")
    try:
        if tpath.exists():
            data = json.loads(tpath.read_text(encoding="utf-8"))
            # support flat and nested
            if isinstance(data, list):
                tags = [str(t).strip().lower() for t in data if str(t).strip()]
            elif isinstance(data, dict):
                container = data
                if isinstance(data.get("tags"), dict):
                    container = data.get("tags") or {}
                raw = []
                if isinstance(container.get("top"), list):
                    raw.extend(container.get("top") or [])
                if isinstance(container.get("tags"), list):
                    raw.extend(container.get("tags") or [])
                tags = [str(t).strip().lower() for t in raw if str(t).strip()]
    except Exception:
        tags = []
    return render_template_string(DETAIL_TEMPLATE, content=html_content, arxiv_id=arxiv_id, tags=tags)


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
    read_map = load_read_map(uid)
    entries_meta = _scan_entries_meta()
    read_entries_meta = [e for e in entries_meta if e["id"] in set(read_map.keys())]
    # allow optional tag filter on read list
    active_tag = (request.args.get("tag") or "").strip().lower() or None
    tag_query = (request.args.get("q") or "").strip().lower()
    if active_tag:
        read_entries_meta = [e for e in read_entries_meta if active_tag in (e.get("tags") or []) or active_tag in (e.get("top_tags") or [])]
    if tag_query:
        def matches_query(tags: list[str] | None, query: str) -> bool:
            if not tags:
                return False
            for t in tags:
                if query in t:
                    return True
            return False
        read_entries_meta = [e for e in read_entries_meta if matches_query(e.get("tags"), tag_query)]
    # tag cloud for read entries
    tag_counts: dict[str, int] = {}
    for e in read_entries_meta:
        for t in (e.get("tags", []) or []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    tag_cloud = sorted(
        ({"name": k, "count": v} for k, v in tag_counts.items()),
        key=lambda item: (-item["count"], item["name"]),
    )
    # pagination for read list
    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 10))
    except Exception:
        per_page = 10
    per_page = max(1, min(per_page, 100))
    total_items = len(read_entries_meta)
    total_pages = max(1, math.ceil(total_items / per_page))
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_entries = read_entries_meta[start:end]

    # render only the current page
    entries = _render_page_entries(page_entries)
    return render_template_string(
        INDEX_TEMPLATE,
        entries=entries,
        uid=uid,
        unread_count=None,
        read_total=None,
        read_today=None,
        show_read=True,
        tag_cloud=tag_cloud,
        active_tag=active_tag,
        tag_query=tag_query,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_items=total_items,
    )

@app.get("/assets/base.css")
def base_css():
    return Response(BASE_CSS, mimetype="text/css")


@app.get("/favicon.svg")
def favicon_svg():
    svg = (
        """
<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 64 64\">
  <defs>
    <linearGradient id=\"gLight\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"#6366f1\"/>
      <stop offset=\"100%\" stop-color=\"#22d3ee\"/>
    </linearGradient>
    <linearGradient id=\"gDark\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"#1d4ed8\"/>
      <stop offset=\"100%\" stop-color=\"#06b6d4\"/>
    </linearGradient>
    <filter id=\"shadow\" x=\"-20%\" y=\"-20%\" width=\"140%\" height=\"140%\">
      <feDropShadow dx=\"0\" dy=\"2\" stdDeviation=\"2\" flood-color=\"#000\" flood-opacity=\".25\"/>
    </filter>
  </defs>
  <style>
    :root { color-scheme: light dark; }
    .light-only { display: block; }
    .dark-only { display: none; }
    .fg { fill: #ffffff; }
    .accent { fill: #f59e0b; }
    @media (prefers-color-scheme: dark) {
      .light-only { display: none; }
      .dark-only { display: block; }
      .fg { fill: #f8fafc; }
      .accent { fill: #fbbf24; }
    }
  </style>

  <!-- vivid gradient background, light/dark aware -->
  <rect class=\"light-only\" x=\"4\" y=\"4\" width=\"56\" height=\"56\" rx=\"14\" fill=\"url(#gLight)\"/>
  <rect class=\"dark-only\"  x=\"4\" y=\"4\" width=\"56\" height=\"56\" rx=\"14\" fill=\"url(#gDark)\"/>

  <!-- stylized book with bookmark and spark -->
  <g filter=\"url(#shadow)\">
    <!-- book body -->
    <rect x=\"17\" y=\"16\" width=\"30\" height=\"34\" rx=\"6\" class=\"fg\"/>
    <!-- page lines -->
    <rect x=\"22\" y=\"22\" width=\"20\" height=\"2\" rx=\"1\" opacity=\".25\"/>
    <rect x=\"22\" y=\"28\" width=\"20\" height=\"2\" rx=\"1\" opacity=\".25\"/>
    <rect x=\"22\" y=\"34\" width=\"14\" height=\"2\" rx=\"1\" opacity=\".25\"/>
    <!-- bookmark ribbon -->
    <path class=\"accent\" d=\"M40 16 v18 l-5-3 l-5 3 V16 z\"/>
  </g>

  <!-- spark -->
  <g transform=\"translate(44 44)\">
    <circle r=\"2.5\" class=\"fg\" opacity=\".3\"/>
    <path class=\"fg\" d=\"M0-4 L1.2-1.2 4 0 1.2 1.2 0 4 -1.2 1.2 -4 0 -1.2 -1.2 Z\"/>
  </g>
</svg>
"""
    ).strip()
    return Response(svg, mimetype="image/svg+xml")


@app.get("/favicon.ico")
def favicon_ico():
    # Serve SVG to avoid 404; modern browsers accept the linked SVG favicon.
    # This keeps network quiet even if the user agent auto-requests /favicon.ico.
    return favicon_svg()


@app.route("/event", methods=["POST"])
def ingest_event():
    uid = request.cookies.get("uid")
    if not uid:
        return jsonify({"error": "no-uid"}), 400
    try:
        payload = request.get_json(silent=True)
        if payload is None:
            raw = request.get_data(as_text=True) or "{}"
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {}
        etype = str(payload.get("type", "")).strip()
        arxiv_id = payload.get("arxiv_id")
        meta = payload.get("meta") or {}
        ts_client = payload.get("ts")
        tz_off_min = payload.get("tz_offset_min")  # minutes where UTC - local
        # keep only click events
        allowed = {"mark_read", "unmark_read", "open_pdf", "login", "logout", "reset", "read_list", "read_more"}
        if etype in allowed:
            ts_local: str | None = None
            try:
                if ts_client:
                    # parse client ts and adjust to local timezone if offset provided
                    # accept 'Z' by replacing with +00:00
                    dt_utc = datetime.fromisoformat(str(ts_client).replace('Z', '+00:00'))
                    if isinstance(tz_off_min, int):
                        tz = timezone(timedelta(minutes=-tz_off_min))
                        dt_local = dt_utc.astimezone(tz)
                        ts_local = dt_local.isoformat(timespec="seconds")
                    else:
                        ts_local = dt_utc.astimezone().isoformat(timespec="seconds")
            except Exception:
                ts_local = None
            append_event(
                uid,
                etype,
                arxiv_id=str(arxiv_id) if arxiv_id else None,
                meta=meta,
                ts=ts_local,
            )
        return jsonify({"status": "ok"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"✅ Serving summaries from {SUMMARY_DIR.resolve()}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 22581)), debug=True)
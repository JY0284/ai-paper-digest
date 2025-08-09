import json
from datetime import datetime

import pytest


def setup_app_dirs(sp, tmp_path):
    sp.USER_DATA_DIR = tmp_path / "user_data"
    sp.SUMMARY_DIR = tmp_path / "summary"
    sp.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    sp.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import summary_page as sp

    setup_app_dirs(sp, tmp_path)
    sp.app.config.update(TESTING=True)
    return sp.app.test_client()


def read_user_json(sp, uid):
    p = sp.USER_DATA_DIR / f"{uid}.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def test_mark_read_saves_local_datetime_with_tz_and_counts_today(tmp_path, monkeypatch):
    import summary_page as sp

    setup_app_dirs(sp, tmp_path)
    sp.app.config.update(TESTING=True)
    client = sp.app.test_client()

    uid = "u1"
    client.set_cookie("uid", uid)

    # mark read for an id
    rid = "2500.00001"
    res = client.post(f"/mark_read/{rid}")
    assert res.status_code == 200

    # verify user data read record
    data = read_user_json(sp, uid)
    assert "read" in data and rid in data["read"]
    ts = data["read"][rid]
    assert isinstance(ts, str) and "T" in ts
    # has timezone offset +HH:MM or -HH:MM
    assert ("+" in ts or "-" in ts[10:]) and ts[-3] == ":"

    # index should show today's count = 1 even with no entries
    res2 = client.get("/")
    assert res2.status_code == 200
    html = res2.data.decode("utf-8")
    assert "今日" in html
    assert ">1<" in html  # the strong tag shows 1 somewhere


def test_event_ingest_filters_non_clicks_and_converts_timezone(tmp_path, monkeypatch):
    import summary_page as sp

    setup_app_dirs(sp, tmp_path)
    sp.app.config.update(TESTING=True)
    client = sp.app.test_client()
    uid = "u2"
    client.set_cookie("uid", uid)

    # non-click event should be ignored
    res = client.post("/event", json={"type": "page_view", "meta": {"page": "index"}})
    assert res.status_code == 200
    data = read_user_json(sp, uid)
    assert data.get("events", []) == []

    # click event open_pdf with client ts and tz offset
    client_ts = "2025-01-02T03:04:05Z"  # UTC
    tz_offset_min = -480  # UTC - local; for UTC+8 locales (e.g., Asia/Shanghai)
    res2 = client.post(
        "/event",
        json={
            "type": "open_pdf",
            "arxiv_id": "2500.00002",
            "meta": {"href": "https://arxiv.org/pdf/2500.00002.pdf"},
            "ts": client_ts,
            "tz_offset_min": tz_offset_min,
        },
    )
    assert res2.status_code == 200
    data = read_user_json(sp, uid)
    evts = data.get("events", [])
    assert len(evts) == 1
    evt = evts[0]
    assert evt["type"] == "open_pdf" and evt["arxiv_id"] == "2500.00002"
    # ts should be converted to local time with +08:00 offset
    ts_str = evt["ts"]
    # parse-able and expected local time
    dt = datetime.fromisoformat(ts_str)
    assert dt.isoformat(timespec="seconds").endswith("+08:00")
    # 03:04:05Z -> 11:04:05+08:00
    assert dt.hour == 11 and dt.minute == 4 and dt.second == 5


def test_event_ingest_allows_only_click_types(tmp_path, monkeypatch):
    import summary_page as sp

    setup_app_dirs(sp, tmp_path)
    sp.app.config.update(TESTING=True)
    client = sp.app.test_client()
    uid = "u3"
    client.set_cookie("uid", uid)

    allowed = ["mark_read", "unmark_read", "open_pdf", "login", "logout", "reset", "read_list", "read_more"]
    for t in allowed:
        res = client.post("/event", json={"type": t, "ts": "2025-01-01T00:00:00Z"})
        assert res.status_code == 200

    # unknown event should not be recorded
    res2 = client.post("/event", json={"type": "foo", "ts": "2025-01-01T00:00:00Z"})
    assert res2.status_code == 200

    data = read_user_json(sp, uid)
    ev_types = [e["type"] for e in data.get("events", [])]
    for t in allowed:
        assert t in ev_types
    assert "foo" not in ev_types



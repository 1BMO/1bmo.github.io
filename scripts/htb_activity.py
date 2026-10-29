#!/usr/bin/env python3
# NOTE: VERSION 7. The Actions log must start with "htb_activity.py v7". On failure it prints a
# "--- probe ---" section (endpoint, HTTP status, JSON key names only - never values).
"""Pull my Hack The Box activity and keep it in htb-activity.json (shown on the Progress page).

Secrets come from the environment only (GitHub Actions secrets), never from files:
  HTB_TOKEN    Hack The Box App Token
  HTB_USER_ID  numeric HTB user id
Optional: HTB_BASE (comma separated base URLs), HTB_OUT (output path).
"""
import json
import os
import sys
import urllib.error
import urllib.request

OUT = os.environ.get("HTB_OUT", "htb-activity.json")
TOKEN = os.environ.get("HTB_TOKEN", "").strip()
UID = os.environ.get("HTB_USER_ID", "").strip()
BASES = [b.strip().rstrip("/") for b in os.environ.get("HTB_BASE", "https://labs.hackthebox.com").split(",") if b.strip()]
PATHS = ["/api/v5/user/profile/activity/"]  # HTB moved/renamed endpoints over time, try both
WHOAMI = "/api/v4/user/info"  # only used to tell a bad token apart from a wrong path
TAG = "HTB Labs"
KEEP = 500


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fail(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer " + TOKEN, "Accept": "application/json, text/plain, */*", "User-Agent": "Mozilla/5.0 (compatible; personal-portfolio-sync)"},
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # network problems
        return 0, str(e)[:120]


HINTS = {
    0: "could not reach the server",
    301: "redirected: the API did not accept the token (it wants a login)",
    302: "redirected: the API did not accept the token (it wants a login)",
    401: "token invalid or expired",
    403: "token not allowed (or blocked)",
    404: "endpoint or user id not found",
    406: "request refused (blocked or wrong Accept header)",
    429: "rate limited, try again later",
}


MAX_PAGES = 10


def pages(base, path):
    """v5 shape: {"data": [...], "meta": {"page", "lastPage", "totalItems"}}. Returns (items, error)."""
    items, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        status, body = fetch("%s%s%s?page=%d" % (base, path, UID, page))
        if status != 200:
            return items, "HTTP %s - %s" % (status, HINTS.get(status, "unexpected status"))
        try:
            j = json.loads(body)
            data = j["data"]
            last = int((j.get("meta") or {}).get("lastPage") or 1)
        except Exception:
            return items, "HTTP 200 but unexpected response shape"
        fresh = 0
        for it in data:
            key = json.dumps(it, sort_keys=True)
            if key not in seen:
                seen.add(key)
                items.append(it)
                fresh += 1
        if page >= last or fresh == 0:
            break
    return items, None


PROBE = [
    "/api/v4/user/profile/content/{id}", "/api/v4/user/profile/bloods/{id}", "/api/v4/user/profile/badges/{id}",
    "/api/v4/user/submissions/machines", "/api/v4/user/submissions/challenges",
    "/api/v4/profile/content/{id}", "/api/v4/profile/bloods/{id}",
    "/api/v5/user/profile/activity/{id}", "/api/v5/user/profile/content/{id}", "/api/v5/user/profile/bloods/{id}",
    "/api/v5/user/profile/basic/{id}", "/api/v5/profile/activity/{id}", "/api/v5/profile/content/{id}",
    "/api/v5/user/activity/{id}", "/api/v5/user/{id}/activity", "/api/v5/user/{id}/owns", "/api/v5/user/dashboard",
    "/api/v5/user/profile/activity/me", "/api/v4/user/profile/activity/me",
]


def shape(x, depth=0):
    """Key names / list sizes only, no values."""
    if isinstance(x, dict):
        if depth >= 2:
            return "{" + ",".join(list(x)[:12]) + "}"
        return "{" + ",".join("%s:%s" % (k, shape(v, depth + 1)) for k, v in list(x.items())[:12]) + "}"
    if isinstance(x, list):
        return "[%d%s]" % (len(x), (" of " + shape(x[0], depth + 1)) if x and depth < 3 else "")
    return type(x).__name__


def probe(base):
    """Runs only after a failure: shows which endpoints exist and their JSON shape (no values)."""
    lines = []
    st, body = fetch(base + WHOAMI)
    try:
        me = json.loads(body).get("info", {}).get("id")
        lines.append("token belongs to user id: %s (HTB_USER_ID is %s -> %s)" % (me, UID, "match" if str(me) == UID else "DIFFERENT"))
    except Exception:
        lines.append("token check body not readable")
    for path in PROBE:
        st, body = fetch(base + path.replace("{id}", UID))
        info = ""
        if st == 200:
            try:
                info = " shape=" + shape(json.loads(body))[:400]
            except Exception:
                info = " (not JSON)"
        lines.append("%s: HTTP %s%s" % (path.replace("{id}", "<id>"), st, info))
    return lines


def get_activity():
    errors = []
    for base in BASES:
        for path in PATHS:
            items, err = pages(base, path)
            if not err or items:
                return items
            errors.append("%s%s: %s" % (base, path, err))
    errors += ["--- probe ---"] + probe(BASES[0])
    fail("\n  ".join([""] + errors))


def day(d):
    return str(d or "")[:10]


def kind(t):
    t = str(t or "").lower()
    if "challenge" in t:
        return "challenge"
    if "root" in t or "system" in t:
        return "root"
    if "user" in t:
        return "user"
    if "sherlock" in t:
        return "sherlock"
    return t or "other"


def build(acts):
    machines, out = {}, {}
    for a in acts:
        name = a.get("name")
        if not name:
            continue
        k, d, fb = kind(a.get("type")), day(a.get("ownDate")), bool(a.get("blood"))
        fbs = " · first blood" if fb else ""
        if k in ("user", "root"):
            m = machines.setdefault(name, {})
            if k not in m or d > m[k][0]:
                m[k] = (d, fb)
        elif k == "challenge":
            out["challenge:%s" % (a.get("id") or name.lower())] = {"title": "Solved " + name, "date": d, "note": "Challenge" + fbs}
        else:
            out["%s:%s" % (k, str(a.get("id") or name).lower())] = {"title": "Completed " + name, "date": d, "note": k.capitalize() + fbs}
    for name, m in machines.items():
        if "root" in m:
            d, fb = m["root"]
            out["machine:" + name.lower()] = {"title": "Rooted " + name, "date": d, "note": "Machine · root" + (" · first blood" if fb else "")}
        else:
            d, fb = m["user"]
            out["machine:" + name.lower()] = {"title": "Got user on " + name, "date": d, "note": "Machine · user flag" + (" · first blood" if fb else "")}
    return {k: dict(v, id=k, tag=TAG) for k, v in out.items()}


def main():
    print("htb_activity.py v7 | commit %s | file %s" % (os.environ.get("GITHUB_SHA", "?")[:7], os.path.abspath(__file__)))
    if not TOKEN or not UID.isdigit():
        fail("HTB_TOKEN and a numeric HTB_USER_ID must be set as environment variables / Actions secrets")
    acts = get_activity()
    types = {}
    for a in acts:
        types[str(a.get("type"))] = types.get(str(a.get("type")), 0) + 1
    print("item types seen: %s" % types)
    new = build(acts)
    try:
        with open(OUT, encoding="utf-8") as f:
            old = {e["id"]: e for e in json.load(f) if isinstance(e, dict) and e.get("id")}
    except (OSError, ValueError):
        old = {}
    merged = dict(old)
    merged.update(new)  # same id = update in place (e.g. user flag later becomes root)
    rows = sorted(merged.values(), key=lambda e: (e.get("date", ""), e.get("title", "")), reverse=True)[:KEEP]
    text = json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
    added = len([k for k in new if k not in old])
    try:
        same = open(OUT, encoding="utf-8").read() == text
    except OSError:
        same = False
    if not same:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(text)
    print("activity items: %d, entries: %d, new: %d, file %s" % (len(acts), len(rows), added, "unchanged" if same else "updated"))


if __name__ == "__main__":
    main()

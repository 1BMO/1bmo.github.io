#!/usr/bin/env python3
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
BASES = [b.strip().rstrip("/") for b in os.environ.get("HTB_BASE", "https://labs.hackthebox.com,https://www.hackthebox.com").split(",") if b.strip()]
PATHS = ["/api/v4/profile/activity/", "/api/v4/user/profile/activity/"]  # HTB moved/renamed endpoints over time, try both
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


def pick(body):
    j = json.loads(body)
    for acts in (j.get("profile", {}).get("activity") if isinstance(j, dict) and isinstance(j.get("profile"), dict) else None,
                 j.get("data") if isinstance(j, dict) else None, j if isinstance(j, list) else None):
        if isinstance(acts, list):
            return acts
    raise ValueError("no activity list")


def get_activity():
    errors = []
    for base in BASES:
        for path in PATHS:
            status, body = fetch(base + path + UID)
            if status == 200:
                try:
                    return pick(body)
                except Exception:
                    errors.append("%s%s: HTTP 200 but unexpected response shape" % (base, path))
            else:
                errors.append("%s%s: HTTP %s - %s" % (base, path, status, HINTS.get(status, "unexpected status")))
        status, _ = fetch(base + WHOAMI)
        errors.append("%s token check (%s): HTTP %s" % (base, WHOAMI, status))
    fail("\n  ".join([""] + errors))


def day(d):
    return str(d or "")[:10]


def build(acts):
    machines, out = {}, {}
    for a in acts:
        ot, ty, name = a.get("object_type"), a.get("type"), a.get("name")
        if not name:
            continue
        d, fb = day(a.get("date")), bool(a.get("first_blood"))
        if ot == "machine":
            m = machines.setdefault(name, {})
            if ty in ("user", "root") and (ty not in m or d > m[ty][0]):
                m[ty] = (d, fb)
        elif ot == "challenge":
            cat = a.get("challenge_category") or ""
            note = "Challenge" + (" · " + cat if cat else "") + (" · first blood" if fb else "")
            out["challenge:%s" % (a.get("id") or name.lower())] = {"title": "Solved " + name, "date": d, "note": note}
        else:
            out["%s:%s" % (ot or "other", (a.get("id") or name).__str__().lower())] = {"title": "Completed " + name, "date": d, "note": (ot or "").capitalize() + (" · first blood" if fb else "")}
    for name, m in machines.items():
        if "root" in m:
            d, fb = m["root"]
            out["machine:" + name.lower()] = {"title": "Rooted " + name, "date": d, "note": "Machine · root" + (" · first blood" if fb else "")}
        elif "user" in m:
            d, fb = m["user"]
            out["machine:" + name.lower()] = {"title": "Got user on " + name, "date": d, "note": "Machine · user flag" + (" · first blood" if fb else "")}
    return {k: dict(v, id=k, tag=TAG) for k, v in out.items()}


def main():
    if not TOKEN or not UID.isdigit():
        fail("HTB_TOKEN and a numeric HTB_USER_ID must be set as environment variables / Actions secrets")
    acts = get_activity()
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

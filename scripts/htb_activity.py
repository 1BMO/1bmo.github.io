#!/usr/bin/env python3
# NOTE: VERSION 13. The Actions log must start with "htb_activity.py v13". On failure it prints a
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
import urllib.parse
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


APP = "https://app.hackthebox.com"
IMG_DIR = os.environ.get("HTB_IMG_DIR", "htb-img")


def page(kind, name):
    return "%s/%s/%s" % (APP, kind, urllib.parse.quote(str(name), safe=""))


def build(acts):
    machines, out = {}, {}
    for a in acts:
        name = a.get("name")
        if not name:
            continue
        k, d, fb = kind(a.get("type")), day(a.get("ownDate")), bool(a.get("blood"))
        fbs = " · first blood" if fb else ""
        av = a.get("avatarUrl") or a.get("avatar") or ""
        if k in ("user", "root"):
            m = machines.setdefault(name, {"id": a.get("id"), "av": av})
            m.setdefault("name", name)
            if k not in m or d > m[k][0]:
                m[k] = (d, fb)
        elif k == "challenge":
            out["challenge:%s" % (a.get("id") or name.lower())] = {"title": "Solved " + name, "date": d, "note": "Challenge" + fbs, "url": page("challenges", name), "_img": ("c%s" % a.get("id"), av, name)}
        else:
            out["%s:%s" % (k, str(a.get("id") or name).lower())] = {"title": "Completed " + name, "date": d, "note": k.capitalize() + fbs}
    for name, m in machines.items():
        base = {"url": page("machines", name), "_img": ("m%s" % m.get("id"), m.get("av"), name)}
        if "root" in m:
            d, fb = m["root"]
            out["machine:" + name.lower()] = dict(base, title="Rooted " + name, date=d, note="Machine · root" + (" · first blood" if fb else ""))
        else:
            d, fb = m["user"]
            out["machine:" + name.lower()] = dict(base, title="Got user on " + name, date=d, note="Machine · user flag" + (" · first blood" if fb else ""))
    return {k: dict(v, id=k, tag=TAG) for k, v in out.items()}


EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif", "image/svg+xml": "svg"}
MAX_IMG = 2 * 1024 * 1024
S3 = "htb-mp-prod-public-storage.s3.eu-central-1.amazonaws.com"
CDN = "cdn.services-k8s.prod.aws.htb.systems"  # HTB image CDN (returned by /api/v4/machine/profile)
IMG_HOSTS = {S3, CDN, "app.hackthebox.com", "labs.hackthebox.com"}  # HTB hosts only
BAD_SVG = (b"<script", b"onload", b"javascript:", b"<foreignobject", b"onerror")
_state = {"pattern": None, "failed": 0}  # which candidate pattern worked; how many machines failed with none


def allowed(u):
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host == "hackthebox.com" or host.endswith(".hackthebox.com") or host in IMG_HOSTS)


def candidates(src):
    """A full URL is used as is. A relative path is tried on several HTB hosts (the real image host is not documented)."""
    src = str(src)
    if src.startswith("http"):
        return [src]
    p = "/" + src.lstrip("/")
    q = p[len("/content"):] if p.startswith("/content/") else p
    return ["https://%s%s" % (CDN, p), "https://labs.hackthebox.com" + p, "https://%s%s" % (S3, p), "https://%s%s" % (S3, q),
            "https://app.hackthebox.com" + p, "https://%s%s.png" % (S3, p), "https://%s%s.png" % (S3, q)]


def try_get(url):
    u = urllib.parse.urlparse(url)
    if not allowed(u):
        return None, None, "host not allowed: " + (u.hostname or "")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; personal-portfolio-sync)", "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=20) as r:
            ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            return ct, r.read(MAX_IMG + 1), None
    except urllib.error.HTTPError as e:
        return None, None, "HTTP %s" % e.code
    except Exception as e:
        return None, None, str(e)[:40]


def save_img(stem, src):
    """Download one HTB image into IMG_DIR (no token sent). Returns (path or None, reason)."""
    if not src or "None" in stem:
        return None, "no image url"
    for e in set(EXT.values()):  # already have it
        if os.path.exists(os.path.join(IMG_DIR, stem + "." + e)):
            return IMG_DIR + "/" + stem + "." + e, "cached"
    cands = candidates(src)
    if len(cands) > 1 and _state["pattern"] is None and _state["failed"] >= 3:
        return None, "skipped: no candidate worked for the first 3"
    order = [_state["pattern"]] if _state["pattern"] is not None else range(len(cands))
    tried = []
    for i in order:
        ct, data, err = try_get(cands[i])
        if err:
            u = urllib.parse.urlparse(cands[i])
            tried.append("%s%s -> %s" % (u.hostname, u.path[:70], err))
            continue
        if ct not in EXT:
            tried.append("%s -> type %s" % (urllib.parse.urlparse(cands[i]).hostname, ct))
            continue
        if len(data) > MAX_IMG:
            return None, "too big"
        if ct == "image/svg+xml" and any(b in data.lower() for b in BAD_SVG):
            return None, "svg rejected (active content)"
        if len(cands) > 1:
            _state["pattern"] = i
        os.makedirs(IMG_DIR, exist_ok=True)
        path = os.path.join(IMG_DIR, stem + "." + EXT[ct])
        with open(path, "wb") as f:
            f.write(data)
        return IMG_DIR + "/" + stem + "." + EXT[ct], "saved"
    if len(cands) > 1 and _state["pattern"] is None:
        _state["failed"] += 1
    return None, "download failed @ " + " | ".join(tried)


def store(stem, ct, data):
    if ct not in EXT:
        return None, "type " + str(ct)
    if len(data) > MAX_IMG:
        return None, "too big"
    if ct == "image/svg+xml" and any(b in data.lower() for b in BAD_SVG):
        return None, "svg rejected"
    os.makedirs(IMG_DIR, exist_ok=True)
    path = os.path.join(IMG_DIR, stem + "." + EXT[ct])
    with open(path, "wb") as f:
        f.write(data)
    return IMG_DIR + "/" + stem + "." + EXT[ct], "saved"


_p2 = {"ok": False, "failed": 0, "shown": False}


def save_img_from_profile(stem, name):
    """Fallback for machines: ask the machine's own profile (same App Token, same API) where its image lives."""
    if not _p2["ok"] and _p2["failed"] >= 3:
        return None, "skipped (profile fallback gave up)"
    st, body = fetch("%s/api/v4/machine/profile/%s" % (BASES[0], urllib.parse.quote(str(name), safe="")))
    vals = {}
    try:
        info = json.loads(body).get("info", {})
        vals = {k: v for k, v in info.items() if isinstance(v, str) and v and any(w in k.lower() for w in ("avatar", "image", "icon", "logo"))}
    except Exception:
        pass
    if not _p2["shown"]:
        _p2["shown"] = True
        print("  profile lookup HTTP %s, image-like fields: %s" % (st, {k: v[:110] for k, v in vals.items()} or "none"))
    for v in vals.values():
        for c in candidates(v):
            ct, data, err = try_get(c)
            if not err and ct in EXT:
                path, why = store(stem, ct, data)
                if path:
                    _p2["ok"] = True
                    return path, "saved (profile)"
    _p2["failed"] += 1
    return None, "profile fallback failed"


def attach_images(new):
    stats, hosts, samples = {}, set(), []
    for e in new.values():
        stem, src, nm = (list(e.pop("_img", (None, None, None))) + [None])[:3]
        if not stem:
            continue
        path, why = save_img(stem, src)
        if not path and stem.startswith("m") and nm and not why.startswith("cached"):
            p2, why2 = save_img_from_profile(stem, nm)
            if p2:
                path, why = p2, why2
        key = why.split(" @ ")[0].split(":")[0]
        stats[key] = stats.get(key, 0) + 1
        if why.startswith("download failed") and len(samples) < 2:
            samples.append(why)
        if path:
            e["img"] = path
        elif why.startswith("host not allowed"):
            hosts.add(why.split(": ")[1])
    if _state["pattern"] is not None:
        print("images: working candidate pattern #%d" % _state["pattern"])
    print("images: %s%s" % (stats, (" | blocked hosts: " + ",".join(sorted(hosts))) if hosts else ""))
    for x in samples:
        print("  sample failure: " + x)


def main():
    print("htb_activity.py v13 | commit %s | file %s" % (os.environ.get("GITHUB_SHA", "?")[:7], os.path.abspath(__file__)))
    if not TOKEN or not UID.isdigit():
        fail("HTB_TOKEN and a numeric HTB_USER_ID must be set as environment variables / Actions secrets")
    acts = get_activity()
    types = {}
    for a in acts:
        types[str(a.get("type"))] = types.get(str(a.get("type")), 0) + 1
    print("item types seen: %s" % types)
    new = build(acts)
    attach_images(new)
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

#!/usr/bin/env python3
"""Write data/werder-bremen.ics and data/vfl-osnabrueck.ics with all fixed upcoming games.

Uses the OpenLigaDB files the data workflow already saves; DFB-Pokal is fetched live (optional).
Games whose kick-off is not fixed yet ("Termin offen") are left out, same rules as index.html.
"""
import json, os, re, sys, unicodedata, urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

DATA = sys.argv[1] if len(sys.argv) > 1 else "data"
NOW = datetime.now(timezone.utc)


def load(name):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower().replace("ß", "ss"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)))


def is_werder(n):
    n = norm(n)
    return "werder" in n or "bremen" in n


def is_vfl(n):
    n = norm(n)
    return "osnabruck" in n or "vflosnabr" in n


def utc(m):
    v = m.get("matchDateTimeUTC")
    if v:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return None


def fixed_horizon(matches):
    # Same idea as computeFixedHorizon in index.html: games re-timed after the initial schedule are fixed
    days = Counter(str(m.get("lastUpdateDateTime") or "")[:10] for m in matches if m.get("lastUpdateDateTime"))
    if not days:
        return None
    base = datetime.fromisoformat(days.most_common(1)[0][0])
    limit = base + timedelta(days=7)
    horizon = 0
    for m in matches:
        if m.get("matchIsFinished") or not m.get("lastUpdateDateTime"):
            continue
        if datetime.fromisoformat(m["lastUpdateDateTime"][:19]) > limit:
            horizon = max(horizon, int((m.get("group") or {}).get("groupOrderID") or 0))
    return horizon or None


def round_no(m):
    return int((m.get("group") or {}).get("groupOrderID") or 0)


def fd_status_by_round(target):
    # football-data.org (1. Bundesliga): SCHEDULED = not fixed yet, TIMED = fixed
    data = load("bundesliga-spiele.json") or {}
    out = {}
    for m in data.get("matches", []) if isinstance(data, dict) else []:
        if target((m.get("homeTeam") or {}).get("name")) or target((m.get("awayTeam") or {}).get("name")):
            out[int(m.get("matchday") or 0)] = m.get("status")
    return out


def changed(m):
    # Stable DTSTAMP (last change of the match) so unchanged files are not re-committed every run
    v = str(m.get("lastUpdateDateTime") or "")[:19]
    try:
        return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


def esc(v):
    return str(v).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    out = []
    while len(line) > 70:
        out.append(line[:70])
        line = " " + line[70:]
    out.append(line)
    return "\r\n".join(out)


def stamp(d):
    return d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def events(matches, target, label, horizon=None, status=None):
    out = []
    for m in matches or []:
        home, away = (m.get("team1") or {}).get("teamName", ""), (m.get("team2") or {}).get("teamName", "")
        if not (target(home) or target(away)) or m.get("matchIsFinished"):
            continue
        start = utc(m)
        if not start or start < NOW:
            continue
        st = (status or {}).get(round_no(m))
        if st == "SCHEDULED" or (st != "TIMED" and horizon is not None and round_no(m) > horizon):
            continue
        rnd = (m.get("group") or {}).get("groupName") or ""
        out.append({"uid": f"oldb-{m.get('matchID')}@werder-vfl-app", "start": start,
                    "title": f"⚽ {home} – {away}", "details": label + (f" · {rnd}" if rnd else ""),
                    "changed": changed(m)})
    return out


def write(path, name, evs):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Werder-VfL-App//DE", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:" + esc(name + " Spiele")]
    for e in sorted(evs, key=lambda e: e["start"]):
        lines += ["BEGIN:VEVENT", "UID:" + e["uid"], "DTSTAMP:" + stamp(e["changed"]), "DTSTART:" + stamp(e["start"]),
                  "DTEND:" + stamp(e["start"] + timedelta(hours=2)), "SUMMARY:" + esc(e["title"]),
                  "DESCRIPTION:" + esc(e["details"]), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(fold(l) for l in lines) + "\r\n")
    print(f"{path}: {len(evs)} Spiele")


bl1 = load("openligadb-bl1-spiele.json") or []
bl2 = load("2bundesliga-spiele.json") or []
cup = []
try:
    with urllib.request.urlopen(f"https://api.openligadb.de/getmatchdata/dfb/{NOW.year}", timeout=20) as r:
        cup = json.load(r)
except Exception as e:
    print("DFB-Pokal nicht verfügbar:", e)

write(os.path.join(DATA, "werder-bremen.ics"), "Werder Bremen",
      events(bl1, is_werder, "Bundesliga", fixed_horizon(bl1), fd_status_by_round(is_werder))
      + events(cup, is_werder, "DFB-Pokal"))
write(os.path.join(DATA, "vfl-osnabrueck.ics"), "VfL Osnabrück",
      events(bl2, is_vfl, "2. Bundesliga", fixed_horizon(bl2)))

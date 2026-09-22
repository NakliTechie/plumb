"""Reproduce the three tables behind the topic-coverage notes.

Public OpenAlex API, no key, ~35 calls. Writes:
  unassigned_by_year.csv        year, unassigned, total
  unassigned_by_source_type.csv type, source_id, source, unassigned
  topics.csv                    4,516 topics with hierarchy + works_count
"""
import csv, json, sys, time, urllib.parse, urllib.request

UA = "openalex-topic-notes (mailto:chirag.patnaik@gmail.com)"
BASE = "https://api.openalex.org"
NULL = "primary_topic.id:null"


def get(url):
    for i in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            print("retry", i, e, file=sys.stderr)
            time.sleep(2 + 2 * i)
    raise SystemExit("gave up on " + url)


def group(filt, key, per_page=200):
    q = {"filter": filt, "group_by": key, "per-page": per_page}
    return get(f"{BASE}/works?{urllib.parse.urlencode(q)}")["group_by"]


def by_year():
    unassigned = {g["key"]: g["count"] for g in group(NULL, "publication_year")}
    total = {g["key"]: g["count"] for g in group("type:!null", "publication_year")}
    with open("unassigned_by_year.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["publication_year", "unassigned_works", "total_works"])
        for y in sorted(unassigned, key=lambda k: -int(k)):
            w.writerow([y, unassigned[y], total.get(y, "")])


def by_source_type():
    rows = []
    for t in ("dataset", "article", "report", "other", "paratext"):
        for g in group(f"{NULL},type:{t}", "primary_location.source.id"):
            if g["count"] < 1000:
                continue
            rows.append([t, g["key"].rsplit("/", 1)[-1], g["key_display_name"], g["count"]])
        time.sleep(0.2)
    rows.sort(key=lambda r: -r[3])
    with open("unassigned_by_source_type.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["type", "source_id", "source", "unassigned_works"])
        w.writerows(rows)


def topics():
    cur, out = "*", []
    while cur:
        q = {"per-page": 200, "cursor": cur}
        d = get(f"{BASE}/topics?{urllib.parse.urlencode(q)}")
        for t in d["results"]:
            sf, fl, dm = t["subfield"], t["field"], t["domain"]
            out.append([
                t["id"].rsplit("/", 1)[-1], t["display_name"],
                sf["id"].rsplit("/", 1)[-1], sf["display_name"],
                fl["id"].rsplit("/", 1)[-1], fl["display_name"],
                dm["id"].rsplit("/", 1)[-1], dm["display_name"],
                t["works_count"], t["cited_by_count"],
                len(t.get("siblings") or []), len(t.get("keywords") or []),
                t.get("created_date", ""), t.get("updated_date", ""),
            ])
        cur = d["meta"].get("next_cursor")
        print("topics", len(out), file=sys.stderr)
        time.sleep(0.12)
    out.sort(key=lambda r: -r[8])
    with open("topics.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["topic_id", "topic", "subfield_id", "subfield", "field_id", "field",
                    "domain_id", "domain", "works_count", "cited_by_count",
                    "sibling_count", "keyword_count", "created_date", "updated_date"])
        w.writerows(out)


if __name__ == "__main__":
    by_year()
    by_source_type()
    topics()

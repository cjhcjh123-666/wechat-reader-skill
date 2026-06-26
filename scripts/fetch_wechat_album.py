#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import html
import json
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49"


def run_curl(url):
    cp = subprocess.run(
        ["curl", "-L", "--silent", "--show-error", "--max-time", "30", "-A", UA, url],
        text=True,
        capture_output=True,
        check=True,
    )
    return cp.stdout


def parse_album_url(url):
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    biz = qs.get("__biz", [""])[0]
    album_id = qs.get("album_id", [""])[0]
    if not biz or not album_id:
        raise SystemExit("Album URL must include __biz and album_id")
    return biz, album_id


def parse_initial_html(text):
    items = []
    for match in re.finditer(
        r"title: '((?:\\'|[^'])*)'.*?create_time: '([^']*)'.*?url: '([^']*)'.*?msgid: '([^']*)'.*?itemidx: '([^']*)'",
        text,
        re.S,
    ):
        title = html.unescape(match.group(1).replace("\\x26", "&"))
        create_time = int(match.group(2))
        items.append(
            {
                "date": dt.datetime.fromtimestamp(create_time).strftime("%Y-%m-%d"),
                "create_time": create_time,
                "title": title,
                "url": html.unescape(match.group(3)),
                "msgid": match.group(4),
                "idx": match.group(5),
                "read_count": "",
            }
        )
    return items


def normalize_item(item):
    create_time = int(item.get("create_time") or 0)
    return {
        "date": dt.datetime.fromtimestamp(create_time).strftime("%Y-%m-%d"),
        "create_time": create_time,
        "title": html.unescape(item.get("title", "")),
        "url": item.get("url", ""),
        "msgid": item.get("msgid", ""),
        "idx": item.get("itemidx", item.get("idx", "")),
        "read_count": item.get("read_count", ""),
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch article metadata from a WeChat album.")
    parser.add_argument("album_url")
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--max-pages", type=int, default=120)
    parser.add_argument("--sleep", type=float, default=0.2)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    biz, album_id = parse_album_url(args.album_url)
    base = "https://mp.weixin.qq.com/mp/appmsgalbum"
    params = {"__biz": biz, "action": "getalbum", "album_id": album_id, "count": "10", "f": "json"}

    items = []
    seen = set()
    begin_msgid = None
    begin_itemidx = None

    for page in range(1, args.max_pages + 1):
        query = params.copy()
        if begin_msgid:
            query["begin_msgid"] = begin_msgid
            query["begin_itemidx"] = begin_itemidx or "1"
        url = base + "?" + urllib.parse.urlencode(query)
        text = run_curl(url)
        try:
            data = json.loads(text)
            article_list = data.get("getalbum_resp", {}).get("article_list", [])
            continue_flag = str(data.get("getalbum_resp", {}).get("continue_flag", "0"))
        except json.JSONDecodeError:
            article_list = parse_initial_html(text)
            continue_flag = "1" if article_list else "0"

        if not article_list:
            break
        new_count = 0
        for raw in article_list:
            item = normalize_item(raw)
            key = (item["msgid"], item["idx"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
            new_count += 1
        begin_msgid = items[-1]["msgid"]
        begin_itemidx = items[-1]["idx"]
        print(f"page {page} got {len(article_list)} new {new_count} last {items[-1]['date']} cont {continue_flag}", flush=True)
        if continue_flag != "1" or new_count == 0:
            break
        time.sleep(args.sleep)

    json_path = output_dir / "wechat_album_articles.json"
    csv_path = output_dir / "wechat_album_articles.csv"
    json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "title", "url", "msgid", "idx", "read_count"])
        writer.writeheader()
        writer.writerows({k: item.get(k, "") for k in writer.fieldnames} for item in items)
    if items:
        print(f"TOTAL {len(items)} range {items[0]['date']} {items[-1]['date']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import csv
import hashlib
import html
import json
import re
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49"

DEFAULT_SKIP = {
    "待认领",
    "待确认",
    "平台方",
    "制作方/版权方",
    "制作方",
    "版权方",
    "承制方",
    "热度",
    "NEW",
    "new",
}
DEFAULT_ALIASES = {
    "杭州刚刚好影": "杭州刚刚好影视",
    "杭州刚刚⋯": "杭州刚刚好影视",
    "杭州刚刚": "杭州刚刚好影视",
    "海鱼星": "海鱼星空",
    "源源滚": "源源滚滚",
    "州创媒新声": "徐州创媒新声",
}
STOP_RE = re.compile(r"(播放|累计|热力|增量|指数|排名|剧查查|数据说明|官方客服|小程序|二维码|DataEye|PS[:：]|统计时间|榜单说明)")


def run(cmd):
    return subprocess.run(cmd, text=True, capture_output=True, check=True)


def run_curl(url, output):
    run(["curl", "-L", "--silent", "--show-error", "--max-time", "30", "-A", UA, "-o", str(output), url])


def load_map(path):
    data = {}
    if not path:
        return data
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            left, right = line.split("=", 1)
            data[left.strip()] = right.strip()
    return data


def load_set(path):
    if not path:
        return set()
    return {line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}


def fetch_article(item, html_dir, force_refetch):
    path = html_dir / f"{item['msgid']}_{item['idx']}.html"
    if force_refetch or not path.exists() or path.stat().st_size < 5000:
        run_curl(item["url"], path)
        time.sleep(0.05)
    text = path.read_text(errors="ignore")
    blocked = "secitptpage/verify.html" in text or "PAGE_MID='mmbizwap:secitptpage" in text
    return path, text, blocked


def js_content(raw):
    match = re.search(r'<div[^>]+id="js_content"[^>]*>(.*?)(?:<script|</body>)', raw, re.S)
    return match.group(1) if match else raw


def image_urls(raw):
    content = js_content(raw)
    urls = []
    for match in re.finditer(r"<img[^>]+>", content):
        tag = match.group(0)
        alt_match = re.search(r'alt=["\']([^"\']*)', tag)
        alt = html.unescape(alt_match.group(1)) if alt_match else ""
        if alt in {"cover_image", "作者头像", "跳转二维码", "#name#"}:
            continue
        src = ""
        for attr in ("data-src", "src", "data-original"):
            src_match = re.search(attr + r'=["\']([^"\']+)', tag)
            if src_match:
                src = html.unescape(src_match.group(1)).replace("&amp;", "&")
                break
        if not src or "pic_blank" in src or "res.wx.qq.com" in src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("http") and src not in urls:
            urls.append(src)
    return urls


def download_image(url, msgid, idx, image_dir):
    digest = hashlib.sha1(url.encode()).hexdigest()[:12]
    path = image_dir / f"{msgid}_{idx:02d}_{digest}.img"
    if not path.exists() or path.stat().st_size < 1000:
        run_curl(url, path)
        time.sleep(0.02)
    return path


def ocr_images(paths, ocr_dir, ocr_tool):
    missing = [path for path in paths if not (ocr_dir / (path.name + ".txt")).exists()]
    if missing:
        print(f"  OCR batch {len(missing)} new image(s)", flush=True)
        cp = run([str(ocr_tool), *[str(path) for path in missing]])
        blocks = re.findall(r"FILE\t(.+?)\n(.*?)\nEND_FILE\t\1", cp.stdout, re.S)
        written = set()
        for file_path, text in blocks:
            path = Path(file_path)
            (ocr_dir / (path.name + ".txt")).write_text(f"FILE\t{file_path}\n{text}\nEND_FILE\t{file_path}\n")
            written.add(path.name)
        for path in missing:
            if path.name not in written:
                (ocr_dir / (path.name + ".txt")).write_text("")
    return [(ocr_dir / (path.name + ".txt")).read_text(errors="ignore") for path in paths]


def clean_name(line):
    line = line.strip()
    line = re.sub(r"^[0-9]+\s*", "", line)
    line = re.sub(r"\s+", "", line)
    line = line.replace("｜", "|").replace("／", "/")
    line = re.sub(r"[()（）【】\[\]{}]", "", line)
    return line.strip(" ,，;；:：|/")


def split_names(line, skip_terms, aliases):
    line = clean_name(line)
    if not line or line in skip_terms or STOP_RE.search(line):
        return []
    if re.fullmatch(r"[-—_]+|[0-9.,万亿wW%]+", line):
        return []
    names = []
    for part in re.split(r"[、/,，;；|&＋+]", line):
        part = clean_name(part)
        if not part or part in skip_terms or STOP_RE.search(part):
            continue
        if re.fullmatch(r"[-—_]+|[0-9.,万亿wW%]+", part):
            continue
        if len(part) < 2 or len(part) > 18:
            continue
        if re.search(r"[一-龥A-Za-z]", part):
            names.append(aliases.get(part, part))
    return names


def makers_from_ocr(text, skip_terms, aliases):
    lines = [clean_name(x) for x in text.splitlines()]
    found = []
    for i, line in enumerate(lines):
        if ("制作" in line and "版权" in line) or "承制方" in line:
            for next_line in lines[i + 1 : i + 45]:
                if STOP_RE.search(next_line):
                    break
                found.extend(split_names(next_line, skip_terms, aliases))
    return found


def write_chart(counter, output_svg, title):
    top = counter.most_common(30)
    width, row_h = 1500, 32
    left, top_pad, right = 260, 52, 120
    height = top_pad + len(top) * row_h + 44
    max_count = max((count for _, count in top), default=1)
    bar_max = width - left - right - 110
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="28" y="32" font-size="22" font-family="Arial, PingFang SC, sans-serif" font-weight="700">{html.escape(title)}</text>',
    ]
    for n, (name, count) in enumerate(top):
        y = top_pad + n * row_h
        bar_w = int(bar_max * count / max_count)
        parts.append(f'<text x="{left - 12}" y="{y + 22}" text-anchor="end" font-size="15" font-family="Arial, PingFang SC, sans-serif">{html.escape(name)}</text>')
        parts.append(f'<rect x="{left}" y="{y + 6}" width="{bar_w}" height="20" fill="#d53b2a"/>')
        parts.append(f'<text x="{left + bar_w + 12}" y="{y + 22}" font-size="15" font-family="Arial, PingFang SC, sans-serif" font-weight="700">{count}</text>')
    parts.append("</svg>")
    output_svg.write_text("\n".join(parts))


def svg_to_pdf(svg_path, pdf_path):
    script = Path(__file__).with_name("svg_to_pdf.swift")
    cache = Path(__file__).parent / ".swift-cache"
    cache.mkdir(exist_ok=True)
    subprocess.run(
        ["swift", str(script), str(svg_path), str(pdf_path)],
        check=True,
        env={**__import__("os").environ, "CLANG_MODULE_CACHE_PATH": str(cache)},
    )


def process_article(item, dirs, ocr_tool, skip_terms, aliases, force_refetch):
    _, raw, blocked = fetch_article(item, dirs["html"], force_refetch)
    if blocked:
        return item, 0, Counter(), [], 0, True
    urls = image_urls(raw)
    image_paths = [download_image(url, item["msgid"], img_no, dirs["images"]) for img_no, url in enumerate(urls, 1)]
    texts = ocr_images(image_paths, dirs["ocr"], ocr_tool)
    article_names = Counter()
    rows = []
    rank_image_count = 0
    for img, text in zip(image_paths, texts):
        names = makers_from_ocr(text, skip_terms, aliases)
        if names:
            rank_image_count += 1
            article_names.update(names)
            rows.extend(
                {
                    "date": item["date"],
                    "title": item["title"],
                    "msgid": item["msgid"],
                    "image": img.name,
                    "maker_or_rightsholder": name,
                }
                for name in names
            )
    return item, len(urls), article_names, rows, rank_image_count, False


def write_outputs(counter, detail_rows, blocked_rows, output_dir, title):
    with (output_dir / "rankmaker_counts.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["maker_or_rightsholder", "appearances"])
        writer.writerows(counter.most_common())
    with (output_dir / "rankmaker_details.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "title", "msgid", "image", "maker_or_rightsholder"])
        writer.writeheader()
        writer.writerows(sorted(detail_rows, key=lambda row: (row["date"], row["msgid"], row["image"]), reverse=True))
    if blocked_rows:
        with (output_dir / "blocked_articles.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "title", "msgid", "url", "reason"])
            writer.writeheader()
            writer.writerows(blocked_rows)
    svg = output_dir / "rankmaker_bar_chart.svg"
    write_chart(counter, svg, title)
    svg_to_pdf(svg, output_dir / "rankmaker_bar_chart.pdf")


def main():
    parser = argparse.ArgumentParser(description="OCR WeChat ranking images and count maker/rightsholder appearances.")
    parser.add_argument("--articles", default="wechat_album_articles.json")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--cutoff", help="Include articles with date >= cutoff, e.g. 2026-03-26")
    parser.add_argument("--max-articles", type=int)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force-refetch", action="store_true")
    parser.add_argument("--ocr-tool", default=None)
    parser.add_argument("--aliases")
    parser.add_argument("--skip-terms")
    parser.add_argument("--title", default="近三个月榜单制作方/版权方出现次数 Top 30")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    dirs = {
        "html": output_dir / "articles_html",
        "images": output_dir / "rank_images",
        "ocr": output_dir / "rank_ocr",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for directory in dirs.values():
        directory.mkdir(exist_ok=True)

    ocr_tool = Path(args.ocr_tool) if args.ocr_tool else Path(__file__).with_name("ocr_vision")
    if not ocr_tool.exists():
        raise SystemExit(f"OCR tool not found: {ocr_tool}. Run scripts/build_ocr_tool.sh first.")

    items = json.loads(Path(args.articles).read_text())
    if args.cutoff:
        items = [item for item in items if item["date"] >= args.cutoff]
    if args.max_articles:
        items = items[: args.max_articles]

    aliases = {**DEFAULT_ALIASES, **load_map(args.aliases)}
    skip_terms = DEFAULT_SKIP | load_set(args.skip_terms)
    counter = Counter()
    detail_rows = []
    blocked_rows = []
    image_count = 0
    started = time.time()
    completed = 0
    print(f"Starting {len(items)} articles with {args.workers} workers", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(process_article, item, dirs, ocr_tool, skip_terms, aliases, args.force_refetch) for item in items]
        for future in as_completed(futures):
            item, url_count, article_names, rows, rank_images, blocked = future.result()
            completed += 1
            image_count += rank_images
            counter.update(article_names)
            detail_rows.extend(rows)
            if blocked:
                blocked_rows.append({**{k: item.get(k, "") for k in ["date", "title", "msgid", "url"]}, "reason": "wechat_security_verify"})
            write_outputs(counter, detail_rows, blocked_rows, output_dir, args.title)
            elapsed = time.time() - started
            eta = (elapsed / completed) * (len(items) - completed)
            print(
                f"DONE {completed}/{len(items)} ({completed / len(items):.1%}) "
                f"{item['date']} images={url_count} makers={sum(article_names.values())} "
                f"elapsed={elapsed/60:.1f}m eta={eta/60:.1f}m"
                + (" BLOCKED" if blocked else ""),
                flush=True,
            )
    print(f"articles={len(items)} ocr_rank_images={image_count} unique_names={len(counter)} blocked={len(blocked_rows)}")


if __name__ == "__main__":
    main()

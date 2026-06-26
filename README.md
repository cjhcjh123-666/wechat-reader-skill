---
name: wechat-rankmaker-ocr
description: Analyze WeChat Official Account album or article pages whose ranking data is embedded in images. Use when Codex needs to crawl mp.weixin.qq.com album/article links, OCR Chinese ranking screenshots, extract maker/rightsholder/producer columns such as 制作方/版权方 or 承制方, count appearances, and export CSV, SVG, or PDF bar charts.
---

# WeChat Rankmaker OCR

Use this skill to turn a WeChat Official Account album into structured ranking-owner statistics when the useful table data is in images rather than HTML text.

## Workflow

1. Use `scripts/fetch_wechat_album.py` to collect article metadata from an album URL.
2. Use `scripts/build_ocr_tool.sh` once per machine to compile the macOS Vision OCR helper.
3. Use `scripts/analyze_rankmakers.py` to fetch selected articles, download in-article images, OCR them, extract `制作方/版权方` and `承制方` columns, and generate outputs.
4. Review `rankmaker_counts.csv` and the chart for OCR noise. Add aliases or skip terms through CLI options or by patching the script when needed.

## Requirements

- macOS is required for the bundled Vision OCR helper.
- Network access is required for `mp.weixin.qq.com` and `mmbiz.qpic.cn`.
- `swift`, `swiftc`, `curl`, and Python 3 must be available.
- Some WeChat article URLs may return `secitptpage/verify.html`; report these as blocked rather than treating them as empty articles.

## Commands

Fetch all album articles:

```bash
python3 scripts/fetch_wechat_album.py "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=...&action=getalbum&album_id=..."
```

Compile OCR helper:

```bash
bash scripts/build_ocr_tool.sh
```

Analyze the latest three months and create CSV/SVG/PDF outputs:

```bash
python3 scripts/analyze_rankmakers.py \
  --articles wechat_album_articles.json \
  --cutoff 2026-03-26 \
  --workers 8 \
  --output-dir outputs
```

Use `--max-articles N` for a small smoke test. Use `--force-refetch` only when cached HTML is a verification page or stale.

## Output Files

The analyzer writes:

- `wechat_album_articles.csv` and `wechat_album_articles.json`: article directory.
- `rankmaker_counts.csv`: name and appearance count.
- `rankmaker_details.csv`: article/image-level extracted names for audit.
- `rankmaker_bar_chart.svg`: editable chart.
- `rankmaker_bar_chart.pdf`: PDF chart.

## Extraction Notes

- Treat `待认领`, `待确认`, `平台方`, numeric values, and metrics like `热度` as noise.
- Count each OCR occurrence because a company can appear in multiple charts or multiple ranks.
- Normalize obvious OCR truncations after inspecting the detail CSV; examples include `杭州刚刚好影` -> `杭州刚刚好影视`.
- Prefer preserving detail rows over aggressive deduplication, so the user can audit which image produced a name.

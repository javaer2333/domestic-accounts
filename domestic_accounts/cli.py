"""Command line interface and portable JSON/CSV reports."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

from . import __version__
from .engine import Result, STATUS_LABELS, query_platform
from .platforms import PLATFORMS


def positive_timeout(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("超时必须是数字") from exc
    if not math.isfinite(number) or not 0 < number <= 120:
        raise argparse.ArgumentTypeError("超时必须大于 0 且不超过 120 秒")
    return number


def bounded_int(low: int, high: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("请输入整数") from exc
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"请输入 {low} 到 {high} 之间的整数")
        return number
    return parse


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="查询国内平台的公开账号：结构化接口匹配、公开主页检索及站内搜索入口。",
        epilog="示例：python domestic.py 笑靥 --platform bilibili,gitee；python domestic.py 554108 --mode id --platform bilibili",
    )
    parser.add_argument("queries", nargs="*", metavar="昵称或ID", help="一个或多个昵称/账号 ID；含空格请用引号")
    parser.add_argument("--version", action="version", version=f"domestic-accounts {__version__}")
    parser.add_argument("--list", action="store_true", dest="list_platforms", help="列出支持的平台和查询方式")
    parser.add_argument("--platform", "-s", action="append", default=[], metavar="PLATFORM",
                        help="平台英文名，逗号分隔，可重复使用；默认全部")
    parser.add_argument("--mode", choices=["nickname", "id"], default="nickname", help="默认按昵称查询；id 按平台主页 ID 查询")
    parser.add_argument("--timeout", type=positive_timeout, default=12, help="单次请求超时秒数，默认 12")
    parser.add_argument("--workers", type=bounded_int(1, 8), default=4, help="并发平台查询数，默认 4，最多 8")
    parser.add_argument("--limit", type=bounded_int(1, 20), default=5, help="每个平台最多显示的候选数，默认 5，最多 20")
    parser.add_argument("--no-web-search", action="store_true", help="禁用搜索引擎检索；无接口的平台仅提供站内搜索入口")
    parser.add_argument("--output-dir", type=Path, default=Path("domestic_results"), help="报告目录，默认 domestic_results")
    parser.add_argument("--format", choices=["json", "csv", "both"], default="both", help="报告格式，默认 both")
    parser.add_argument("--no-save", action="store_true", help="仅在终端显示，不保存报告")
    return parser


def save_reports(results: list[Result], directory: Path, report_format: str, settings: dict) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    prefix = "accounts_" + now.strftime("%Y%m%dT%H%M%S_%fZ")
    paths = []
    if report_format in {"json", "both"}:
        path = directory / (prefix + ".json")
        payload = {
            "tool": "domestic-accounts", "version": __version__, "created_at": now.isoformat(),
            "settings": settings,
            "notice": "同名账号不代表同一个人。仅公开接口精确匹配标记 matched；公开索引和 HTTP 200 页面均为待核实候选。未发现结果不证明账号不存在。",
            "results": [r.to_dict() for r in results],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    if report_format in {"csv", "both"}:
        path = directory / (prefix + ".csv")
        # UTF-8 BOM lets common spreadsheet applications display Chinese correctly.
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            columns = ["query", "mode", "platform", "platform_name", "status", "name", "account_id", "url", "source", "matched", "evidence", "search_url", "note", "total"]
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for result in results:
                base = {key: getattr(result, key) for key in ("query", "mode", "platform", "platform_name", "status", "search_url", "note", "total")}
                for profile in result.profiles or [None]:
                    row = dict(base)
                    if profile:
                        row.update(vars(profile))
                    # Prevent account names from being interpreted as spreadsheet formulas.
                    row = {k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else v for k, v in row.items()}
                    writer.writerow(row)
        paths.append(path)
    return paths


def print_result(result: Result) -> None:
    print(f"\n[{result.platform_name}] {STATUS_LABELS[result.status]} · 查询：{result.query}")
    for profile in result.profiles:
        marker = "精确匹配" if profile.matched else "待核实"
        display_name = " ".join(profile.name.split())
        print(f"  [{marker}] {display_name}" + (f" (ID: {profile.account_id})" if profile.account_id else ""))
        print(f"    {profile.url}")
    if result.total is not None:
        print(f"  接口报告的相关结果数：{result.total}；当前展示 {len(result.profiles)} 条")
    print(f"  说明：{result.note}")
    print(f"  站内搜索：{result.search_url}")


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.list_platforms:
        print("平台英文名         中文名        昵称查询方式            主页ID查询")
        for key, platform in PLATFORMS.items():
            method = "公开接口 + 索引备用" if platform.adapter != "web" else "公开索引 + 站内入口"
            print(f"{key:<18} {platform.name:<10} {method:<20} {'支持' if platform.id_url else '暂不支持'}")
        return 0
    if not args.queries:
        parser.error("请提供昵称或 ID，或使用 --list 查看平台")
    queries = list(dict.fromkeys(q.strip() for q in args.queries))
    if len(queries) > 20 or any(not q or len(q) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in q) for q in queries):
        parser.error("每次最多查询 20 个值；每个值须为 1～128 个可见字符")
    selected = list(dict.fromkeys(k.strip().lower() for group in args.platform for k in group.split(","))) if args.platform else list(PLATFORMS)
    unknown = [name for name in selected if name not in PLATFORMS]
    if unknown:
        parser.error("未知平台：" + ", ".join(unknown) + "；使用 --list 查看支持的平台")
    tasks = [(query, PLATFORMS[key]) for query in queries for key in selected]
    results_by_task = {}
    print(f"国内账号查询 · {len(queries)} 个查询值 × {len(selected)} 个平台 · 模式 {args.mode}", flush=True)
    print("同名账号可能属于不同的人；搜索引擎收录结果需要打开主页核实。", flush=True)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(query_platform, platform, query, args.mode, timeout=args.timeout,
                            limit=args.limit, web_search=not args.no_web_search): (query, platform.key)
                for query, platform in tasks
            }
            for index, future in enumerate(as_completed(futures), 1):
                key = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    # A broken adapter must not discard other platforms' completed reports.
                    query, platform_key = key
                    platform = PLATFORMS[platform_key]
                    from urllib.parse import quote
                    result = Result(platform.key, platform.name, query, args.mode, "error",
                                    platform.search_url.format(query=quote(query, safe="")),
                                    note=f"平台查询异常（{type(exc).__name__}）；请检查接口是否发生变化")
                results_by_task[key] = result
                print(f"  [{index}/{len(tasks)}] {result.platform_name} · {result.query}：{STATUS_LABELS[result.status]}", flush=True)
    except KeyboardInterrupt:
        print("\n查询已中断。", file=sys.stderr)
        return 130
    results = [results_by_task[(query, platform.key)] for query, platform in tasks]
    for result in results:
        print_result(result)
    counts = Counter(r.status for r in results)
    exact_count = sum(p.matched for r in results for p in r.profiles)
    print(f"\n完成：接口精确匹配 {exact_count} 个账号；" + "，".join(f"{STATUS_LABELS[k]} {v} 项" for k, v in counts.items()))
    if not args.no_save:
        try:
            paths = save_reports(results, args.output_dir, args.format, {
                "queries": queries, "platforms": selected, "mode": args.mode,
                "timeout": args.timeout, "limit": args.limit, "web_search": not args.no_web_search,
            })
        except OSError as exc:
            print(f"无法保存报告（{type(exc).__name__}），以上终端结果仍有效。", file=sys.stderr)
            return 1
        for path in paths:
            print(f"报告：{path.resolve()}")
    return 1 if all(r.status in {"error", "blocked", "unsupported"} for r in results) else 0

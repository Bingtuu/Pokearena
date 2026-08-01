"""解析 mitmproxy flow 文件，输出接口摘要，供分析小程序 API 用。

用法：
    .venv/Scripts/python.exe dump_flows.py <flows文件> [--host 关键字] [--full N]

输出：
    默认：按 host+path 去重的接口清单（方法、状态码、请求/响应大小、Content-Type）
    --host：只看 host 含关键字的请求
    --full N：完整打印第 N 条（请求头/体 + 响应头/体，截断到 2000 字符）
"""
from __future__ import annotations

import argparse
import sys
from collections import OrderedDict

from mitmproxy import http
from mitmproxy.io import FlowReader

SKIP_CONTENT_TYPES = ("image/", "font/", "video/")


def iter_flows(path: str):
    with open(path, "rb") as f:
        for flow in FlowReader(f).stream():
            if isinstance(flow, http.HTTPFlow):
                yield flow


def is_interesting(flow: http.HTTPFlow) -> bool:
    """过滤静态资源，只留疑似 API 调用。"""
    ct = flow.response.headers.get("content-type", "") if flow.response else ""
    if any(ct.startswith(s) for s in SKIP_CONTENT_TYPES):
        return False
    path = flow.request.path.lower()
    if any(path.endswith(ext) for ext in (".js", ".css", ".png", ".jpg", ".svg", ".woff2", ".ico")):
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("flows", help="mitmproxy 导出的 flows 文件路径")
    ap.add_argument("--host", default="", help="host 关键字过滤")
    ap.add_argument("--full", type=int, default=None, help="完整打印第 N 条（从 1 开始）")
    args = ap.parse_args()

    flows = [f for f in iter_flows(args.flows) if is_interesting(f)]
    if args.host:
        flows = [f for f in flows if args.host in f.request.host]

    if args.full is not None:
        flow = flows[args.full - 1]
        req = flow.request
        print(f"=== #{args.full} {req.method} {req.pretty_url}")
        print("--- 请求头 ---")
        for k, v in req.headers.items():
            print(f"  {k}: {v}")
        print("--- 请求体 ---")
        print((req.get_text() or "")[:2000])
        if flow.response:
            print(f"--- 响应 {flow.response.status_code} ---")
            for k, v in flow.response.headers.items():
                print(f"  {k}: {v}")
            print((flow.response.get_text() or "")[:2000])
        return 0

    seen: OrderedDict[tuple, list] = OrderedDict()
    for f in flows:
        key = (f.request.method, f.request.host, f.request.path.split("?")[0])
        status = f.response.status_code if f.response else "-"
        ct = (f.response.headers.get("content-type", "") if f.response else "").split(";")[0]
        size = len(f.response.content or b"") if f.response else 0
        seen.setdefault(key, []).append((status, ct, size))

    print(f"共 {len(flows)} 条请求，去重后 {len(seen)} 个接口：\n")
    for i, ((method, host, path), hits) in enumerate(seen.items(), 1):
        statuses = {s for s, _, _ in hits}
        cts = {c for _, c, _ in hits}
        print(
            f"[{i}] {method} {host}{path}  x{len(hits)}  "
            f"状态={sorted(statuses)}  类型={sorted(cts)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
B站数据提交与传输工具

本地分析 + 报告传输一站式。
分析完成后自动将报告通过 HTTP POST 传到文案生成机，或提交到分析服务器。

用法：
  # 完整流程：分析 -> HTTP 传到文案生成机
  python submit_client.py --send-url http://host:18236/

  # 只分析
  python submit_client.py --analyze

  # 分析 + 保存副本
  python submit_client.py --analyze --save ./backup.txt

  # 提交到远程分析服务器（旧模式，备用）
  python submit_client.py --server http://192.168.1.100:18235

  # 仅检查连通性
  python submit_client.py --check --send-url http://host:18236/
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_base_dir = Path(__file__).parent.resolve()
if os.environ.get("BILI_PORTABLE", "1") == "0":
    _base_dir = Path.home() / ".bilibili_fav"

BILI_FAV_HOME = _base_dir
REPORT_PREFIX = "analysis_report_"


def get_uid(uid_arg: str = None) -> str:
    """获取 UID：优先参数，其次文件"""
    if uid_arg:
        return uid_arg
    uid_file = BILI_FAV_HOME / "bili_uid.txt"
    if uid_file.exists():
        return uid_file.read_text().strip()
    return ""


def run_analyze(uid: str) -> str:
    """运行本地分析，返回报告文件路径"""
    print(f"\n  正在本地分析 (Ollama qwen2.5:7b)...")
    from analyze import save_report

    report_path = save_report(uid)
    print(f"[完成] 分析完成: {report_path}")
    return str(report_path)


def http_send_report(report_path: str, url: str) -> bool:
    """通过 HTTP POST (multipart/form-data) 发送报告文件到目标机"""
    url = url.rstrip("/")
    if not url.endswith("/"):
        url = url + "/"

    boundary = "----BiliReportBoundary"
    filename = os.path.basename(report_path)
    with open(report_path, "rb") as f:
        file_data = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    print(f"  HTTP 发送: {report_path} -> {url}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_text = resp.read().decode("utf-8").strip()
            if resp.status == 200:
                print(f"[完成] 传输成功 ({resp_text})")
                return True
            else:
                print(f"[错误] 服务器返回 {resp.status}: {resp_text}")
                return False
    except urllib.error.HTTPError as e:
        print(f"[错误] HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}")
        return False
    except urllib.error.URLError as e:
        print(f"[错误] 连接失败 ({url}): {e.reason}")
        return False
    except Exception as e:
        print(f"[错误] 传输异常: {e}")
        return False


def submit_to_server(server_url: str, uid: str, save_path: str = None) -> dict:
    """提交数据到分析服务器（旧模式）"""
    payload = collect_crawl_data(uid)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    url = server_url.rstrip("/") + "/api/analyze"
    print(f"  提交 {len(payload['favorites'])} 个收藏夹 + {len(payload['dynamics'])} 条动态")
    print(f"   目标: {url}")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        print(f"[错误] 服务器返回 {e.code}: {body}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[错误] 连接失败 ({url}): {e.reason}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[错误] 响应解析失败: {e}")
        sys.exit(1)

    if result.get("status") == "success":
        print(f"[完成] 分析完成! (报告长度: {len(result.get('report', ''))} 字符)")
        if save_path:
            Path(save_path).write_text(result.get("report", ""), encoding="utf-8")
            print(f"   本地副本: {save_path}")
    else:
        print(f"[错误] 分析失败: {result.get('message', '未知错误')}")
        sys.exit(1)

    return result


def collect_crawl_data(uid: str) -> dict:
    """收集本地采集数据"""
    data_dir = BILI_FAV_HOME / f"data_{uid}"
    dynamics_dir = BILI_FAV_HOME / f"dynamics_{uid}"

    favorites = {}
    if data_dir.exists():
        for fname in sorted(os.listdir(data_dir)):
            if fname.endswith(".json") and fname != ".progress.json":
                path = data_dir / fname
                videos = json.loads(path.read_text(encoding="utf-8"))
                for v in videos:
                    v.pop("_favorite", None)
                favorites[fname.replace(".json", "")] = videos

    dynamics = []
    simple_path = dynamics_dir / f"uid_{uid}_simple.json"
    if simple_path.exists():
        dynamics = json.loads(simple_path.read_text(encoding="utf-8"))

    return {"uid": uid, "favorites": favorites, "dynamics": dynamics}


def health_check_http(url: str):
    """测试目标 HTTP 服务器是否可达（发一个最小 POST 确认）"""
    url = url.rstrip("/") + "/"
    print(f"  测试连接: {url}")
    boundary = "----HealthCheck"
    body = f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[完成] 连接正常 (HTTP {resp.status})")
            return True
    except urllib.error.HTTPError as e:
        # 4xx/5xx 但有响应说明服务器在线
        print(f"[完成] 服务器在线 (HTTP {e.code})")
        return True
    except urllib.error.URLError as e:
        print(f"[错误] 连接失败 ({url}): {e.reason}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="B站数据提交与传输工具")
    parser.add_argument("--uid", type=str, help="用户UID（默认从 bili_uid.txt 读取）")
    parser.add_argument("--analyze", action="store_true", help="先运行本地 Ollama 分析")
    parser.add_argument("--send-url", type=str, help="文案机接收地址，如 http://192.168.1.100:18236/")
    parser.add_argument("--server", type=str, help="分析服务器地址（HTTP 模式，备用）")
    parser.add_argument("--save", type=str, help="保存报告本地副本")
    parser.add_argument("--check", action="store_true", help="仅检查 HTTP 连通性")
    args = parser.parse_args()

    uid = get_uid(args.uid)
    if not uid:
        print("[错误] 未指定 UID，且 bili_uid.txt 不存在")
        sys.exit(1)
    print(f"  UID: {uid}")

    # === 仅检查连通性 ===
    if args.check:
        if args.send_url:
            health_check_http(args.send_url)
        if args.server:
            from submit_client import health_check
            health_check(args.server)
        sys.exit(0)

    # === 分析报告路径 ===
    report_path = None

    # 如果有 --analyze 或没有 --send-url（本地模式默认分析）
    if args.analyze or (not args.server and not args.send_url):
        report_path = run_analyze(uid)
    elif args.server:
        # 没有 --analyze 但有 --server：直接提交采集数据
        submit_to_server(args.server, uid, args.save)
        sys.exit(0)

    # 如果没分析也指定了发送，尝试找已有报告
    if not report_path and (args.send_url or args.save):
        pid = BILI_FAV_HOME / f"{REPORT_PREFIX}{uid}.json"
        if pid.exists():
            report_path = str(pid)
            print(f"  使用已有报告: {report_path}")
        else:
            print("[错误] 没有找到报告，请先运行 --analyze")
            sys.exit(1)

    # === HTTP 传输 ===
    if args.send_url and report_path:
        success = http_send_report(report_path, args.send_url)
        if not success:
            sys.exit(1)

    # === 保存本地副本 ===
    if args.save and report_path:
        import shutil
        shutil.copy2(report_path, args.save)
        print(f"  副本已保存: {args.save}")

    if report_path:
        print(f"\n  报告文件: {report_path}")

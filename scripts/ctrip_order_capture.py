#!/usr/bin/env python3
"""Print Ctrip order-detail pages to individual PDFs through a logged-in browser."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


TRUTHY = {"1", "true", "yes", "y", "skip", "空开", "是"}
DEFAULT_LOGIN_URL = "https://ct.ctrip.com/"


def default_profile() -> Path:
    return Path.home() / ".codex" / "state" / "ctrip-order-capture"


def default_pwcli() -> Path:
    override = os.environ.get("PWCLI")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codex" / "skills" / "playwright" / "scripts" / "playwright_cli.sh"


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "_", value.strip())
    return cleaned.strip("._") or "unknown"


def parse_result(output: str) -> dict:
    match = re.search(r"### Result\s*\n(.*?)\n### Ran Playwright code", output, re.S)
    if not match:
        return {"status": "cli_error", "error": output.strip()[-1000:]}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {"status": "cli_error", "error": match.group(1)[:1000]}


class Pwcli:
    def __init__(self, executable: Path, session: str):
        if not executable.exists():
            raise SystemExit(
                f"找不到 Playwright CLI 包装脚本：{executable}\n"
                "请安装 Codex playwright Skill，或用 --pwcli 指定 playwright_cli.sh。"
            )
        self.executable = executable
        self.session = session

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        command = ["bash", str(self.executable), "--session", self.session, *args]
        completed = subprocess.run(command, text=True, capture_output=True)
        if check and completed.returncode != 0:
            message = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(message or f"命令失败：{' '.join(args)}")
        return completed

    def is_open(self) -> bool:
        return self.run("snapshot", check=False).returncode == 0

    def open(self, url: str, profile: Path, headed: bool) -> None:
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        args = ["open", url, "--browser", "chrome", "--persistent", "--profile", str(profile)]
        if headed:
            args.append("--headed")
        self.run(*args)


def load_orders(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"seq", "order_no"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise SystemExit("订单清单必须包含 seq 和 order_no 两列。")
        rows = []
        for line_no, row in enumerate(reader, start=2):
            seq = (row.get("seq") or "").strip()
            order_no = (row.get("order_no") or "").strip()
            if not seq:
                raise SystemExit(f"第 {line_no} 行缺少 seq。")
            if not order_no and (row.get("skip") or "").strip().lower() not in TRUTHY:
                raise SystemExit(f"第 {line_no} 行缺少 order_no；如需空开，请在 skip 列填写“空开”。")
            rows.append(
                {
                    "seq": seq,
                    "order_no": order_no,
                    "person": (row.get("person") or "").strip(),
                    "skip": (row.get("skip") or "").strip(),
                }
            )
    return sorted(rows, key=lambda item: (int(item["seq"]) if item["seq"].isdigit() else 10**9, item["seq"]))


def refuse_git_output(output_dir: Path) -> None:
    current = output_dir.resolve()
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            raise SystemExit(
                f"输出目录位于 Git 仓库内：{output_dir}\n"
                "订单资料含敏感信息，请选择仓库外的目录。"
            )


def capture_code(
    order_no: str,
    orders_url: str,
    pdf_path: Path,
    wait_ms: int,
    search_selector: str,
    submit_selector: str,
    ready_selector: str,
) -> str:
    settings = {
        "orderNo": order_no,
        "ordersUrl": orders_url,
        "pdfPath": str(pdf_path),
        "waitMs": wait_ms,
        "searchSelector": search_selector,
        "submitSelector": submit_selector,
        "readySelector": ready_selector,
    }
    payload = json.dumps(settings, ensure_ascii=False)
    return f"""async (page) => {{
  const cfg = {payload};
  const sleep = ms => page.waitForTimeout(ms);
  const visibleFirst = async (scope, selectors) => {{
    for (const selector of selectors.filter(Boolean)) {{
      const matches = scope.locator(selector);
      const count = Math.min(await matches.count(), 8);
      for (let i = 0; i < count; i += 1) {{
        const candidate = matches.nth(i);
        if (await candidate.isVisible().catch(() => false)) return candidate;
      }}
    }}
    return null;
  }};
  try {{
    await page.emulateMedia({{ media: 'screen' }});
    await page.goto(cfg.ordersUrl, {{ waitUntil: 'domcontentloaded', timeout: 45000 }});
    await sleep(cfg.waitMs);
    const scopes = [page, ...page.frames().filter(frame => frame !== page.mainFrame())];
    const searchSelectors = [
      cfg.searchSelector,
      'input[placeholder*="订单号"]',
      'input[placeholder*="订单"]',
      'input[name*="order" i]',
      'input[id*="order" i]',
      'input[type="search"]'
    ];
    let search = null;
    let searchScope = page;
    for (const scope of scopes) {{
      search = await visibleFirst(scope, searchSelectors);
      if (search) {{ searchScope = scope; break; }}
    }}
    if (!search) {{
      const text = await page.locator('body').innerText().catch(() => '');
      const loginLike = /登录|验证码|扫码登录|sign\s*in/i.test(text) || /login|passport/i.test(page.url());
      return {{ status: loginLike ? 'login_required' : 'selector_needed', url: page.url(), error: '未找到订单号输入框' }};
    }}
    await search.fill(cfg.orderNo);
    if (cfg.submitSelector) {{
      const submit = await visibleFirst(searchScope, [cfg.submitSelector]);
      if (!submit) throw new Error('未找到指定查询按钮');
      await submit.click();
    }} else {{
      await search.press('Enter');
    }}
    await sleep(cfg.waitMs);

    let orderText = null;
    for (const scope of scopes) {{
      const candidate = scope.getByText(cfg.orderNo, {{ exact: false }}).first();
      if (await candidate.isVisible().catch(() => false)) {{ orderText = candidate; break; }}
    }}
    if (!orderText) {{
      return {{ status: 'not_found', url: page.url(), error: '查询结果未显示该订单号' }};
    }}

    const directLink = orderText.locator('xpath=ancestor-or-self::a[1]');
    if (await directLink.count() && await directLink.first().isVisible().catch(() => false)) {{
      await directLink.first().click();
      await sleep(cfg.waitMs);
    }} else {{
      const row = orderText.locator('xpath=ancestor::*[self::tr or @role="row" or contains(@class,"order")][1]');
      if (await row.count()) {{
        const detail = row.first().getByText(/订单详情|查看详情|详情|查看/, {{ exact: false }}).first();
        if (await detail.isVisible().catch(() => false)) {{
          await detail.click();
          await sleep(cfg.waitMs);
        }}
      }}
    }}

    for (const label of ['展开全部', '查看全部', '更多详情', '展开']) {{
      const buttons = page.getByText(label, {{ exact: true }});
      const count = Math.min(await buttons.count(), 10);
      for (let i = 0; i < count; i += 1) {{
        const button = buttons.nth(i);
        if (await button.isVisible().catch(() => false)) await button.click().catch(() => {{}});
      }}
    }}
    if (cfg.readySelector) {{
      await page.locator(cfg.readySelector).first().waitFor({{ state: 'visible', timeout: 15000 }});
    }}
    await sleep(cfg.waitMs);
    for (let i = 0; i < 25; i += 1) {{
      const before = await page.evaluate(() => window.scrollY);
      await page.evaluate(() => window.scrollBy(0, Math.max(window.innerHeight * 0.8, 500)));
      await sleep(120);
      const after = await page.evaluate(() => window.scrollY);
      if (after === before) break;
    }}
    await page.evaluate(() => window.scrollTo(0, 0));
    await sleep(300);
    const bodyText = await page.locator('body').innerText().catch(() => '');
    if (!bodyText.includes(cfg.orderNo)) {{
      return {{ status: 'verification_failed', url: page.url(), error: '详情页未能再次核验订单号' }};
    }}
    await page.emulateMedia({{ media: 'print' }});
    try {{
      await page.pdf({{
        path: cfg.pdfPath,
        format: 'A4',
        printBackground: true,
        margin: {{ top: '10mm', right: '8mm', bottom: '10mm', left: '8mm' }}
      }});
    }} catch (error) {{
      await page.emulateMedia({{ media: 'screen' }}).catch(() => {{}});
      return {{ status: 'print_failed', url: page.url(), error: error.message }};
    }}
    await page.emulateMedia({{ media: 'screen' }});
    return {{ status: 'printed', url: page.url(), title: await page.title() }};
  }} catch (error) {{
    return {{ status: 'error', url: page.url(), error: error.message }};
  }}
}}"""


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    fields = ["seq", "order_no", "person", "status", "pdf", "url", "error"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def command_login(args: argparse.Namespace) -> int:
    runner = Pwcli(args.pwcli, args.session)
    if runner.is_open():
        runner.run("goto", args.url)
    else:
        runner.open(args.url, args.profile, headed=True)
    print("已打开独立的携程订单打印浏览器。请完成登录并进入“我的订单”页面，然后复制该页面网址用于 capture 命令。")
    return 0


def command_capture(args: argparse.Namespace) -> int:
    output_dir = args.output_dir.expanduser().resolve()
    refuse_git_output(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    orders = load_orders(args.input.expanduser().resolve())
    runner = Pwcli(args.pwcli, args.session)
    if not runner.is_open():
        runner.open(args.orders_url, args.profile, headed=args.headed)

    manifest: list[dict[str, str]] = []
    printed: dict[str, dict[str, str]] = {}
    for order in orders:
        seq = order["seq"]
        order_no = order["order_no"]
        base = f"{safe_filename(seq).zfill(3)}_{safe_filename(order_no)}"
        if order["person"]:
            base += f"_{safe_filename(order['person'])}"
        row = {"seq": seq, "order_no": order_no, "person": order["person"], "status": "", "pdf": "", "url": "", "error": ""}
        if order["skip"].strip().lower() in TRUTHY:
            row["status"] = "skipped"
            manifest.append(row)
            write_manifest(output_dir / "capture_manifest.csv", manifest)
            continue
        if order_no in printed:
            first = printed[order_no]
            row.update({"status": f"reused_from_seq_{first['seq']}", "pdf": first["pdf"], "url": first["url"]})
            manifest.append(row)
            write_manifest(output_dir / "capture_manifest.csv", manifest)
            continue

        pdf = output_dir / f"{base}.pdf"
        partial_pdf = output_dir / f".{base}.partial.pdf"
        partial_pdf.unlink(missing_ok=True)
        code = capture_code(order_no, args.orders_url, partial_pdf, args.wait_ms, args.search_selector, args.submit_selector, args.ready_selector)
        completed = runner.run("run-code", code, check=False)
        result = parse_result(completed.stdout or completed.stderr)
        row["status"] = str(result.get("status", "cli_error"))
        row["url"] = str(result.get("url", ""))
        row["error"] = str(result.get("error", ""))
        if row["status"] == "printed" and partial_pdf.exists() and partial_pdf.stat().st_size > 1024:
            partial_pdf.replace(pdf)
            row["pdf"] = pdf.name
        elif row["status"] == "printed":
            row["status"] = "print_failed"
            row["error"] = "浏览器未生成有效 PDF 文件"
        partial_pdf.unlink(missing_ok=True)
        if row["status"] == "printed" and row["pdf"]:
            printed[order_no] = row.copy()
        manifest.append(row)
        write_manifest(output_dir / "capture_manifest.csv", manifest)
        print(f"序号 {seq} / 订单 {order_no}: {row['status']}")
        if row["status"] == "login_required":
            print("登录状态失效，已停止。请重新运行 login，登录后再继续。")
            break

    write_manifest(output_dir / "capture_manifest.csv", manifest)
    failures = [row for row in manifest if row["status"] not in {"printed", "skipped"} and not row["status"].startswith("reused_from_seq_")]
    print(f"完成：{len(manifest)} 条；异常：{len(failures)} 条；清单：{output_dir / 'capture_manifest.csv'}")
    return 2 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按明细序号逐单打印携程订单详情为独立 PDF。")
    parser.add_argument("--pwcli", type=Path, default=default_pwcli(), help="playwright_cli.sh 路径")
    parser.add_argument("--session", default="ctrip-order-capture", help="Playwright CLI 会话名")
    parser.add_argument("--profile", type=Path, default=default_profile(), help="独立登录资料目录（不要放入 Git 仓库）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="打开独立浏览器供用户登录")
    login.add_argument("--url", default=DEFAULT_LOGIN_URL)
    login.set_defaults(func=command_login)

    capture = subparsers.add_parser("capture", help="按 CSV 序号逐单打印订单详情")
    capture.add_argument("--input", type=Path, required=True, help="包含 seq、order_no 的 CSV")
    capture.add_argument("--orders-url", required=True, help="登录后的“我的订单”页面网址")
    capture.add_argument("--output-dir", type=Path, required=True, help="仓库外的输出目录")
    capture.add_argument("--wait-ms", type=int, default=2500, help="每次查询/跳转后的等待毫秒数")
    capture.add_argument("--headed", action="store_true", help="会话未启动时显示浏览器")
    capture.add_argument("--search-selector", default="", help="页面改版时指定订单号输入框 CSS 选择器")
    capture.add_argument("--submit-selector", default="", help="页面改版时指定查询按钮 CSS 选择器")
    capture.add_argument("--ready-selector", default="", help="详情加载完成标志的 CSS 选择器")
    capture.set_defaults(func=command_capture)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.profile = args.profile.expanduser().resolve()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

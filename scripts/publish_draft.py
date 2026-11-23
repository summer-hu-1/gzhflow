#!/usr/bin/env python3
"""gzhflow 推草稿箱工具（publish_draft）。

调用微信官方 API 把排版好的 HTML + 封面图推送到公众号草稿箱：
  1. 获取 access_token（凭 AppID + AppSecret）
  2. 上传正文图片（media/uploadimg）→ 重写为 https URL
  3. 上传封面素材（media/add_material, type=image）
  4. draft/add 创建草稿

⚠️ 个人主体公众号 2025-07 起无法 API 直接发布（freepublish 回收），
   本工具只推草稿箱，用户在「公众号助手 App」手动点发布。

凭证只从环境变量 WECHAT_APP_ID/WECHAT_APP_SECRET 读取

用法:
    python scripts/publish_draft.py <排版.html> --title "标题" \
        --author "作者" --summary "摘要" --cover cover.jpg --dry-run
    python scripts/publish_draft.py <排版.html> --title "标题" \
        --author "作者" --summary "摘要" --cover cover.jpg

退出码: 0 = 成功, 非0 = 失败
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Windows GBK 控制台兼容：强制 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_BASE = "https://api.weixin.qq.com"
ROOT = Path(__file__).resolve().parent.parent


# ============ 凭证读取 ============
def load_credentials(args=None):
    """Only environment variables are accepted: never pass secrets in CLI or Git."""
    app_id = os.environ.get("WECHAT_APP_ID", "")
    app_secret = os.environ.get("WECHAT_APP_SECRET", "")
    if not app_id or not app_secret or "your_" in app_id or "your_" in app_secret:
        print("❌ 请配置 WECHAT_APP_ID 和 WECHAT_APP_SECRET 环境变量", file=sys.stderr)
        sys.exit(2)
    return app_id, app_secret


# ============ API 调用 ============
def _die_api_error(e: Exception, context: str) -> None:
    """Never print request URLs, headers, query parameters or raw responses."""
    status = f"HTTP {e.code}" if isinstance(e, urllib.error.HTTPError) else "network error"
    print(f"❌ 微信 API {context}: {status}（敏感响应已隐藏）", file=sys.stderr)
    sys.exit(1)


def _die_wechat_error(resp: dict, context: str) -> None:
    """Print only the error code; errmsg can contain sensitive values."""
    code = resp.get("errcode", "unknown")
    hint = {
        40164: "API IP 未列入白名单",
        48001: "当前接口未授权",
        40001: "凭证错误或令牌失效",
        45009: "接口请求次数超限",
    }.get(code, "检查接口权限和微信后台")
    print(f"❌ {context}失败: errcode={code}；{hint}", file=sys.stderr)
    sys.exit(1)


def api_get(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        _die_api_error(e, "api_get")


def api_post(url: str, data: dict, files: dict = None) -> dict:
    if files:
        # multipart 上传素材
        boundary = "----gzhflowBoundary" + os.urandom(8).hex()
        body = b""
        for key, (fname, content, ctype) in files.items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{key}"; filename="{fname}"\r\n'.encode()
            body += f"Content-Type: {ctype}\r\n\r\n".encode()
            body += content + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    else:
        req = urllib.request.Request(
            url, data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        _die_api_error(e, "api_post")


def _content_type(path: Path) -> str:
    """按文件后缀判断上传 Content-Type（.png→image/png、.gif→image/gif，默认 image/jpeg）。"""
    return {
        ".png": "image/png",
        ".gif": "image/gif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(path.suffix.lower(), "image/jpeg")


def get_token(app_id: str, app_secret: str) -> str:
    """Stable token API keeps AppSecret out of URLs."""
    resp = api_post(f"{API_BASE}/cgi-bin/stable_token", {
        "grant_type": "client_credential",
        "appid": app_id,
        "secret": app_secret,
        "force_refresh": False,
    })
    if resp.get("errcode") not in (None, 0, "0") or not resp.get("access_token"):
        _die_wechat_error(resp, "获取稳定 token")
    return resp["access_token"]

# ============ 上传图片 ============
def upload_image(token: str, img_path: Path) -> str:
    """上传正文图片（media/uploadimg），返回 https URL。"""
    content = img_path.read_bytes()
    url = f"{API_BASE}/cgi-bin/media/uploadimg?access_token={token}"
    resp = api_post(url, {}, files={"media": (img_path.name, content, _content_type(img_path))})
    if "url" not in resp:
        _die_wechat_error(resp, "上传正文图片")
    return resp["url"]


def upload_cover(token: str, cover_path: Path) -> str:
    """上传封面为永久素材（material/add_material），返回 media_id（thumb_media_id 用）。

    注意：路径是 /cgi-bin/material/add_material（永久素材），不是 /cgi-bin/media/...
    （media/ 下没有 add_material，写错会 404）。个人订阅号拥有此基础权限。
    """
    content = cover_path.read_bytes()
    url = f"{API_BASE}/cgi-bin/material/add_material?access_token={token}&type=image"
    resp = api_post(url, {}, files={"media": (cover_path.name, content, _content_type(cover_path))})
    if "media_id" not in resp:
        _die_wechat_error(resp, "上传封面")
    return resp["media_id"]


def upload_html_images(token: str, html_text: str, base_dir: Path) -> str:
    """扫描 HTML 中的本地图片，上传并重写为 https URL。"""
    def _replace(m):
        src = m.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        p = base_dir / src
        if not p.exists():
            print(f"⚠️ 图片不存在，保留原路径: {src}", file=sys.stderr)
            return m.group(0)
        url = upload_image(token, p)
        print(f"  ↳ 上传图片 {src} → {url[:60]}…")
        return f'src="{url}"'
    return re.sub(r'src="([^"]+)"', _replace, html_text)


# ============ 发布偏好（config/publish.yaml 的 publish 段） ============
def load_publish_config() -> dict:
    """极简读取 config/publish.yaml 的 publish.default_author / publish.open_comment。"""
    cfg = ROOT / "config" / "publish.yaml"
    result = {"default_author": "", "open_comment": True}
    if not cfg.exists():
        return result
    text = cfg.read_text(encoding="utf-8")
    m = re.search(r"default_author\s*[:=]\s*[\"']?([^\"'\n]+)", text)
    if m:
        result["default_author"] = m.group(1).strip().strip("\"'")
    m = re.search(r"open_comment\s*[:=]\s*(\w+)", text)
    if m:
        result["open_comment"] = m.group(1).strip().lower() in ("true", "1", "yes")
    return result


# ============ 主流程 ============
def main():
    ap = argparse.ArgumentParser(description="gzhflow 推草稿箱（微信官方 API）")
    ap.add_argument("html", help="排版 HTML 路径")
    ap.add_argument("--title", required=True, help="文章标题")
    ap.add_argument("--author", help="作者（默认 config 或 frontmatter）")
    ap.add_argument("--summary", help="摘要（默认截取正文前 120 字）")
    ap.add_argument("--cover", help="封面图路径（2.35:1 ≈ 900x383；缺省读 frontmatter 的 coverImage）")
    ap.add_argument("--no-cover", action="store_true", help="已废弃：draft/add 强制要求封面 thumb_media_id，无封面必报 40007")
    ap.add_argument("--confirm-create-draft", action="store_true", help="明确授权本次写入草稿箱")
    ap.add_argument("--dry-run", action="store_true", help="验证全链路但不推送（取 token 前返回）")
    args = ap.parse_args()

    if args.no_cover:
        print("❌ --no-cover 已废弃：draft/add 接口强制要求封面 thumb_media_id，"
              "不带封面必然返回 40007 invalid media_id。请用 --cover 指定封面图", file=sys.stderr)
        sys.exit(2)

    html_path = Path(args.html)
    if not html_path.exists():
        print(f"❌ HTML 不存在: {html_path}", file=sys.stderr)
        sys.exit(2)

    # 元数据：CLI 参数 > frontmatter（md 侧车文件）
    html_text = html_path.read_text(encoding="utf-8")
    author = args.author
    summary = args.summary
    title = args.title
    cover = Path(args.cover) if args.cover else None

    # 侧车 md：优先同名 .md，其次工作流产物 draft.md（两者都在 output_dir 内）
    md_side = next(
        (p for p in (html_path.with_suffix(".md"), html_path.parent / "draft.md") if p.exists()),
        None,
    )
    if md_side:
        md_text = md_side.read_text(encoding="utf-8")
        fm = re.search(r"^---\s*\n(.*?)\n---", md_text, re.S)
        if fm:
            for key, pat in (("title", r"title\s*:\s*(.+)"),
                             ("author", r"author\s*:\s*(.+)"),
                             ("description", r"description\s*:\s*(.+)"),
                             ("coverImage", r"coverImage\s*:\s*(.+)")):
                m = re.search(pat, fm.group(1))
                val = m.group(1).strip() if m else ""
                if not val or val == "null":
                    continue
                if key == "title":
                    title = title or val
                elif key == "author":
                    author = author or val
                elif key == "description":
                    summary = summary or val
                elif key == "coverImage" and cover is None:
                    cover = html_path.parent / val

    if cover is None:
        print("❌ 未指定封面：请用 --cover，或在 frontmatter 写 coverImage"
              "（draft/add 强制要求封面 thumb_media_id，无封面报 40007）", file=sys.stderr)
        sys.exit(2)
    if not cover.exists():
        print(f"❌ 封面不存在: {cover}", file=sys.stderr)
        sys.exit(2)

    # 作者兜底：--author > frontmatter author > config/publish.yaml 的 publish.default_author > 空
    pub_cfg = load_publish_config()
    if not author:
        author = pub_cfg["default_author"] or ""

    if args.dry_run:
        print("✅ dry-run 通过：参数/文件就绪（未取 token，零风险）")
        print(f"   title: {title}")
        print(f"   author: {author or '(未指定)'}")
        print(f"   summary: {(summary or '')[:60]}{'…' if summary and len(summary) > 60 else ''}")
        print(f"   cover: {cover}")
        sys.exit(0)

    if not args.confirm_create_draft:
        print("❌ 未提供 --confirm-create-draft：未调用微信 API", file=sys.stderr)
        sys.exit(2)

    app_id, app_secret = load_credentials(args)
    token = get_token(app_id, app_secret)
    print("✅ 已获取 access_token")

    # 上传正文图片并重写
    html_remote = upload_html_images(token, html_text, html_path.parent)
    if html_remote != html_text:
        print("✅ 正文图片已上传并重写为 https URL")

    # 上传封面（material/add_material 永久素材，个人订阅号实测可用，2026-10-13；
    # 上传失败直接退出——没有 thumb_media_id 的草稿 draft/add 也会被拒 40007）
    cover_media_id = upload_cover(token, cover)
    print(f"✅ 封面已上传: {cover_media_id}")

    # 摘要兜底：截取正文前 120 字
    if not summary:
        text_only = re.sub(r"<[^>]+>", "", html_remote)
        summary = re.sub(r"\s+", "", text_only)[:120]

    # 创建草稿
    article = {
        "title": title,
        "author": author or "",
        "digest": summary,
        "content": html_remote,
        "content_source_url": "",
        "need_open_comment": 1 if pub_cfg["open_comment"] else 0,
    }
    if cover_media_id:
        article["thumb_media_id"] = cover_media_id
    resp = api_post(f"{API_BASE}/cgi-bin/draft/add?access_token={token}", {"articles": [article]})
    if resp.get("errcode") not in (0, "0", None):
        _die_wechat_error(resp, "创建草稿")
    if "media_id" in resp:
        print(f"✅ 已推送到草稿箱: {resp['media_id']}")
        print("   请在「公众号助手 App → 草稿箱」检查后手动发布（个人号无法 API 直接发布）")
        sys.exit(0)
    _die_wechat_error(resp, "创建草稿")


if __name__ == "__main__":
    main()

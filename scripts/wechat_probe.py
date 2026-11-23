#!/usr/bin/env python3
"""Read-only WeChat Official Account API permission probe.

Only calls POST /cgi-bin/stable_token and GET /cgi-bin/draft/count.
This module never uploads media, creates drafts, publishes, or mass-sends.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.weixin.qq.com"
TIMEOUT_SECONDS = 15
HINTS = {
    40001: "access_token 无效或过期",
    40013: "AppID 无效",
    40125: "AppSecret 不正确",
    40164: "API 调用出口 IP 不在微信白名单",
    45009: "接口调用频率受限",
    48001: "当前账号未被授权使用该接口",
}


class ProbeError(Exception):
    def __init__(self, code, phase):
        self.code = code
        self.phase = phase
        super().__init__(f"{phase}: {code}")


def _request_json(method, path, *, payload=None, token=None):
    """Call only approved API paths, return parsed JSON without logging secrets."""
    routes = {
        ("POST", "/cgi-bin/stable_token"),
        ("GET", "/cgi-bin/draft/count"),
    }
    if (method, path) not in routes:
        raise ProbeError("route_not_allowed", path)
    url = API_BASE + path
    if token is not None:
        url += "?" + urllib.parse.urlencode({"access_token": token})
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        # HTTP errors often include a URL containing a token. Never print the raw exception.
        raise ProbeError("network_or_http_error", path) from None
    try:
        result = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ProbeError("invalid_json", path) from None
    if not isinstance(result, dict):
        raise ProbeError("invalid_response_shape", path)
    error_code = result.get("errcode", 0)
    if error_code not in (0, "0", None):
        try:
            code = int(error_code)
        except (ValueError, TypeError):
            code = "unknown_wechat_error"
        raise ProbeError(code, path)
    return result


def stable_token(app_id, app_secret):
    if not app_id or not app_secret:
        raise ProbeError("credentials_missing", "stable_token")
    result = _request_json(
        "POST", "/cgi-bin/stable_token",
        payload={
            "grant_type": "client_credential",
            "appid": app_id,
            "secret": app_secret,
            "force_refresh": False,
        },
    )
    value = result.get("access_token")
    if not isinstance(value, str) or not value:
        raise ProbeError("token_missing", "stable_token")
    return value


def draft_count(token):
    if not token:
        raise ProbeError("token_missing", "draft/count")
    result = _request_json("GET", "/cgi-bin/draft/count", token=token)
    count = result.get("total_count")
    if type(count) is not int or count < 0:
        raise ProbeError("draft_count_missing", "draft/count")
    return count


def run_check(environ=None):
    env = os.environ if environ is None else environ
    token = stable_token(env.get("WECHAT_APP_ID"), env.get("WECHAT_APP_SECRET"))
    count = draft_count(token)
    return {"token": "ok", "draft_count": "ok", "total_count": count,
            "draft_add": "not_tested", "public_publish": "disabled"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="微信只读权限检测（禁止草稿写入及发表）")
    parser.add_argument("--check", action="store_true", required=True,
                        help="仅获取 stable_token、读取草稿总数")
    args = parser.parse_args(argv)
    try:
        report = run_check()
    except ProbeError as exc:
        report = {
            "status": "failed", "phase": exc.phase, "errcode": exc.code,
            "hint": HINTS.get(exc.code, "检查账号权限、凭证和网络配置"),
            "draft_add": "not_tested", "public_publish": "disabled",
        }
        print(json.dumps(report, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

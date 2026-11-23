# Codex Cloud + 微信草稿箱：安全接入 V0.3

## 实际状态与边界

- 本仓库仍然是公开仓库：**不要提交个人文章、微信凭证或任何私密素材**。
- 私人文章与风格库建议放在私有 `summer-hu-1/WeChatAutoRank`；该仓库目前是完整的 gzhflow 副本，不是数据库服务。
- 个人订阅号的 `draft/count` 与 `draft/add` 权限必须通过账号实际调用验证。
- **严禁正式发表/群发**；即使成功创建草稿，也不代表文章已经公开发布。

## 1. 先运行完全离线的检查

```bash
python scripts/validate_repo.py
python -m unittest discover -s tests -v
python scripts/md2wechat.py skills/gzh-design/assets/sample-article.md --theme zen -o /tmp/wechat-preview.html
python scripts/validate_gzh_html.py /tmp/wechat-preview.html
```

这些操作不请求微信、也不会写入微信草稿箱。Codex Cloud 里可以先不设置任何 Secret 运行。

## 2. 微信后台的人工配置

1. 登录微信公众平台 https://mp.weixin.qq.com/ 或微信开发者平台 https://developers.weixin.qq.com/platform 。
2. 检查公众号主体类型、AppID、开发密钥管理与草稿接口权限。
3. 检查微信 API IP 白名单。执行位置若是 Codex Cloud，先确认其实际出口 IP；动态或不确定出口建议改用拥有固定 IP 的执行器。
4. 在 Codex 环境的**密钥管理**中分别添加 `WECHAT_APP_ID` 与 `WECHAT_APP_SECRET`，不要作为普通环境变量写入仓库、任务文本或日志。
5. 对实际需要的运行阶段单独开放 `api.weixin.qq.com` 外网访问。具体安全设置遵循 Codex Cloud 当前官方文档。

Codex Cloud 的初始化脚本不应访问真实微信接口，避免密钥意外暴露。Secret 注入范围和任务执行阶段必须在你的 Codex UI 中确认。

## 3. 只读权限检查

仅在具备凭证、网络及正确白名单后：

```bash
python scripts/wechat_probe.py --check
```

请求顺序严格限定：
- `POST https://api.weixin.qq.com/cgi-bin/stable_token`
- `GET https://api.weixin.qq.com/cgi-bin/draft/count`

输出不会打印 AppSecret 或 access_token。成功读取草稿数量 **不能证明** `draft/add` 可用。

| 报错 | 判断 |
| --- | --- |
| 48001 | 当前账号未授权对应接口 |
| 40164 | 出口 IP 未加入白名单 |
| 40001 | token 无效或过期 |
| 40013 | AppID 错误 |
| 40125 | AppSecret 错误 |
| network_or_http_error | 网络、HTTP、白名单之外的访问问题 |
| credentials_missing | 缺少凭证环境变量 |

日志对上游错误信息做脱敏，不显示原始请求/响应正文。

## 4. 生成 HTML 与不写入的 dry-run

```bash
python scripts/md2wechat.py skills/gzh-design/assets/sample-article.md --theme zen -o /tmp/article.html
python scripts/validate_gzh_html.py /tmp/article.html
python scripts/publish_draft.py /tmp/article.html --title "测试文章" --cover /path/to/cover.jpg --dry-run
```

`--dry-run` 仅做本地文件与参数检查，不证明微信 API 已授权。

## 5. 仅在人工确认后创建非公开草稿

必须先完成只读探测、备妥封面并核对排版 HTML。随后由用户**单独明确确认**本次创建草稿，再运行：

```bash
python scripts/publish_draft.py /tmp/article.html --title "测试文章" --cover /path/to/cover.jpg --confirm-create-draft
```

此命令会上传图片并调用 `draft/add`，可能消耗素材额度；不会调用 `freepublish/submit` 或任何群发接口。返回 `media_id` 后还需进公众号后台核对真实草稿。**接口超时后不要自动重试**：可能已经创建成功，先人工检查草稿箱，避免重复稿。

如果个人订阅号没有 `draft/add` 权限：只交付本地 HTML、封面和正文图片，在微信官方编辑器中由用户手动保存草稿。

## 6. Codex Cloud 执行指令

> 先审查 AGENTS.md、skills/gzhflow/SKILL.md 与本文件。默认只运行离线单元测试、排版验证。不要读取真实私有文章、不要调用公众号写入接口。获得用户明确授权后再执行只读 probe；第二次明确授权后才允许上传图片和创建非公开草稿。禁止正式发表、群发、修改或删除原有草稿。任何变更通过独立分支和 PR 交付，不合并主分支。

## 当前验证状态

- 代码在功能分支内提供：本地模拟测试脚本与只读 probe。
- 尚未获取真实微信账号凭证，**未执行真实微信 API 测试，也未创建草稿**。
- 若 CI 不可用或未运行，不能将模拟测试标为通过。

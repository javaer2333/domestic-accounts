# 国内平台公开账号查询工具（domestic-accounts）

一个受 [Sherlock](https://github.com/sherlock-project/sherlock) 启发的 Python 命令行工具，用于按**显示昵称**或**平台主页 ID** 查询国内常见平台的公开账号信息。

它不是“人肉搜索”工具：只访问无需登录的公开接口和公开网页，不绕过验证码，不携带登录状态，也不会把同名账号断言为同一个人。

## 功能

- 覆盖 16 个国内平台：哔哩哔哩、微博、知乎、抖音、小红书、快手、豆瓣、百度贴吧、CSDN、博客园、简书、Gitee、稀土掘金、SegmentFault、开源中国、V2EX。
- **B站、Gitee** 使用公开用户接口做结构化匹配，能返回账号 ID 和主页；B站支持数字 UID 反查，Gitee 支持登录名反查。
- 其他平台通过公开搜索索引查找被收录的个人主页，并附上站内搜索入口；部分平台支持按主页 ID 检查。
- 并发查询、超时与并发数可调、每个平台限制结果条数。
- 结果导出为 JSON 和 CSV（UTF-8 BOM，便于表格软件打开）。
- 明确区分：“接口精确匹配”“待核实候选”“未找到”“访问受限”“查询失败”，避免把普通网页或验证页误报为账号。
- 内置离线测试（全部网络请求均被 mock），便于回归。

## 安装

需要 Python 3.10+。

```bash
git clone <本仓库地址>
cd domestic-accounts

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 也可以安装为命令
.venv/bin/python -m pip install -e .
```

## 快速使用

```bash
# 查看支持的平台
.venv/bin/python domestic.py --list

# 按昵称查询全部平台，自动保存 JSON + CSV
.venv/bin/python domestic.py '小黄没烦恼'

# 只查指定平台，每个平台最多展示 10 条
.venv/bin/python domestic.py '小黄没烦恼' --platform bilibili,gitee --limit 10

# 多个昵称/账号变体一起查
.venv/bin/python domestic.py '小黄没烦恼' xiaohuang --platform bilibili,gitee

# 已知 B站 UID / Gitee 登录名
.venv/bin/python domestic.py 629673508 --mode id --platform bilibili
.venv/bin/python domestic.py someuser --mode id --platform gitee

# 不提交搜索引擎查询，只生成站内搜索入口
.venv/bin/python domestic.py '小黄没烦恼' --no-web-search

# 指定报告目录 / 只输出到终端
.venv/bin/python domestic.py '小黄没烦恼' --output-dir out
.venv/bin/python domestic.py '小黄没烦恼' --no-save
```

安装为命令后可直接使用 `domestic-accounts '小黄没烦恼'`，参数完全相同。含空格的昵称请加引号。

## 命令行参数

| 参数 | 说明 |
| --- | --- |
| `--list` | 列出平台及查询方式 |
| `--platform/-s` | 平台英文名，逗号分隔或重复指定；默认全部 |
| `--mode nickname\|id` | 默认按昵称；`id` 按平台主页 ID 查询 |
| `--timeout` | 单次请求超时秒数，默认 12，范围 (0, 120] |
| `--workers` | 并发平台数，默认 4，范围 1–8 |
| `--limit` | 每个平台最多展示条数，默认 5，范围 1–20 |
| `--no-web-search` | 禁用公开索引检索 |
| `--output-dir` | 报告目录，默认 `domestic_results` |
| `--format json\|csv\|both` | 报告格式，默认 both |
| `--no-save` | 不保存报告 |

## 平台与查询方式

| 参数名 | 平台 | 昵称查询 | 主页 ID 查询 |
| --- | --- | --- | --- |
| `bilibili` | 哔哩哔哩 | 公开用户搜索接口，失败时回退公开索引 | 数字 UID |
| `gitee` | Gitee | 公开用户搜索接口，失败时回退公开索引 | 登录名 |
| `weibo` | 微博 | 公开索引 + 用户搜索入口 | 数字 UID |
| `zhihu` | 知乎 | 公开索引 + 用户搜索入口 | `/people/` 后的 token |
| `douyin` | 抖音 | 公开索引 + 用户搜索入口 | `MS4wLjAB…` 格式 sec_uid（非抖音号） |
| `xiaohongshu` | 小红书 | 公开索引 + 内容搜索入口 | 24 位十六进制主页 ID（非小红书号） |
| `kuaishou` | 快手 | 公开索引 + 视频搜索入口 | 暂不支持 |
| `douban` | 豆瓣 | 公开索引 + 用户搜索入口 | 暂不支持 |
| `tieba` | 百度贴吧 | 公开索引 + 帖子搜索入口 | 暂不支持 |
| `csdn` | CSDN | 公开索引 + 用户搜索入口 | 博客用户名 |
| `cnblogs` | 博客园 | 公开索引 + 博文搜索入口 | 博客用户名 |
| `jianshu` | 简书 | 公开索引 + 用户搜索入口 | 12 位十六进制 ID |
| `juejin` | 稀土掘金 | 公开索引 + 内容搜索入口 | 数字用户 ID |
| `segmentfault` | SegmentFault | 公开索引 + 内容搜索入口 | `/u/` 后的账号名 |
| `oschina` | 开源中国 | 公开索引 + 内容搜索入口 | `/u/` 后的数字 ID |
| `v2ex` | V2EX | 公开索引 + 站内搜索入口 | `/member/` 后的用户名 |

公开索引通过 Bing RSS 查询，只保留平台域名下、符合个人主页路径规则、且标题或摘要包含查询词的条目，排除文章页、搜索页和外部链接。

## 状态含义

| 状态 | 含义 |
| --- | --- |
| `matched` | 公开接口返回的昵称/账号与查询值精确匹配；逐条看 `profiles[].matched` |
| `candidates` | 公开索引、相关用户或仅能打开的主页，需要人工核实 |
| `not_found` | 接口未返回用户，或 ID 地址返回 404；不代表全平台不存在 |
| `no_candidates` | 公开索引没有符合规则的主页，仍可使用站内入口 |
| `blocked` | 反爬、登录要求、限流或接口风控，不计为命中 |
| `error` | 超时、网络错误或响应结构变化，不计为命中 |
| `search_required` | 无直接查询渠道或发生跳转，已提供站内入口 |
| `unsupported` | 不支持的 ID 格式 |

**重要：** `matched` 仅表示名称/ID 相同，不能证明多个账号属于同一个人。未找到也不证明账号不存在。

## 报告

默认写入 `domestic_results/`，文件名带 UTC 时间戳，不覆盖历史结果：

- JSON：包含查询参数、每个平台的状态、备注、候选列表、来源与证据。
- CSV：每个候选一行；无候选的平台也会保留状态和入口。

不保存响应正文、Cookie 或登录信息。

退出码：`0` 查询完成；`1` 所有平台均失败/受限/不支持，或报告写入失败；`2` 参数错误；`130` 用户中断。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -p test_domestic_accounts.py -v
```

测试不访问网络：所有响应均为 mock，覆盖 HTML 200 不等于命中、反爬/登录页、404/500、跳转、无效 ID、搜索结果域名与路径过滤、XML 安全（DOCTYPE/ENTITY）、贴吧身份参数、小红书访问令牌等边界。

## 项目结构

```
domestic.py                      # 便捷入口
domestic_accounts/
  __main__.py                    # python -m domestic_accounts
  cli.py                         # 参数、并发、JSON/CSV 导出
  engine.py                      # 接口适配、公开索引、状态判定
  platforms.py                   # 平台清单、主页/ID 规则
tests/
  test_domestic_accounts.py      # 离线测试
```

## 边界与合规

- 只查询公开信息，不提供手机号反查、私人账号定位、密码找回或绕过隐私设置的能力。
- 微信个人号、QQ 私人账号、支付宝账户没有可用的公开“按昵称搜人”接口；客户端内的手机号查找受对方隐私设置限制。
- 请遵守目标平台的服务条款与当地法律，仅将结果用于合法目的；频繁请求可能触发限流。
- 同名账号可能属于不同的人，请勿据此进行骚扰、人肉或误导性推断。

## 许可

MIT

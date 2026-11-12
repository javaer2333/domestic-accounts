"""Declarative platform rules; importing this module performs no network I/O.

``search_url`` takes an already URL-quoted query. Search results may include
content, rather than accounts: callers must check both the hostname and
``profile_pattern`` against the parsed URL path before accepting a profile.
``id_pattern`` matches a bare, platform-specific account identifier, never a
nickname or a complete URL. Patterns intentionally accept only known formats.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    domains: tuple[str, ...]
    search_url: str
    profile_pattern: str
    id_url: str | None = None
    id_pattern: str | None = None
    adapter: str = "web"


# Gitee and CNBlogs put account names directly below the site root. Exclude
# application routes so search/login pages cannot masquerade as accounts.
_GITEE_RESERVED = (
    r"(?:about|api|assets|blog|codes|dashboard|discover|enterprises|enterprise|"
    r"explore|help|issues|login|logout|notifications|oauth|organizations|"
    r"password|pricing|projects|pull_requests|search|settings|signup|"
    r"snippets|stars|terms|users)"
)
_CNBLOGS_RESERVED = (
    r"(?:aggsite|album|articles|blog|blogs|cate|category|contact|default|"
    r"editor|feed|group|help|history|home|images|jobs|login|news|p|post|"
    r"posts|q|register|search|site|skins|tags|team|user|users|u|wz)"
)


PLATFORMS: dict[str, Platform] = {
    "bilibili": Platform(
        key="bilibili",
        name="哔哩哔哩",
        domains=("space.bilibili.com",),
        search_url="https://search.bilibili.com/upuser?keyword={query}",
        profile_pattern=r"^/[1-9][0-9]*/?\Z",
        id_url="https://space.bilibili.com/{id}",
        id_pattern=r"^[1-9][0-9]*\Z",
        adapter="bilibili",
    ),
    "weibo": Platform(
        key="weibo",
        name="微博",
        domains=("weibo.com",),
        search_url="https://s.weibo.com/user?q={query}",
        profile_pattern=r"^/(?:u/)?[1-9][0-9]*/?\Z",
        id_url="https://weibo.com/u/{id}",
        id_pattern=r"^[1-9][0-9]*\Z",
    ),
    "zhihu": Platform(
        key="zhihu",
        name="知乎",
        domains=("zhihu.com",),
        search_url="https://www.zhihu.com/search?type=people&q={query}",
        profile_pattern=r"^/people/[A-Za-z0-9_-]+/?\Z",
        id_url="https://www.zhihu.com/people/{id}",
        id_pattern=r"^[A-Za-z0-9_-]+\Z",
    ),
    "douyin": Platform(
        key="douyin",
        name="抖音",
        domains=("douyin.com",),
        search_url="https://www.douyin.com/search/{query}?type=user",
        profile_pattern=r"^/user/MS4wLjAB[A-Za-z0-9_-]{16,}/?\Z",
        id_url="https://www.douyin.com/user/{id}",
        id_pattern=r"^MS4wLjAB[A-Za-z0-9_-]{16,}\Z",
    ),
    "xiaohongshu": Platform(
        key="xiaohongshu",
        name="小红书",
        domains=("xiaohongshu.com",),
        # The web search landing page searches notes by default.
        search_url="https://www.xiaohongshu.com/search_result?keyword={query}",
        profile_pattern=r"^/user/profile/[0-9a-fA-F]{24}/?\Z",
        id_url="https://www.xiaohongshu.com/user/profile/{id}",
        id_pattern=r"^[0-9a-fA-F]{24}\Z",
    ),
    "kuaishou": Platform(
        key="kuaishou",
        name="快手",
        domains=("kuaishou.com",),
        # Public web search is a video search, not a claimed user-search API.
        search_url="https://www.kuaishou.com/search/video?searchKey={query}",
        profile_pattern=r"^/profile/[A-Za-z0-9_-]+/?\Z",
    ),
    "douban": Platform(
        key="douban",
        name="豆瓣",
        domains=("douban.com",),
        search_url="https://www.douban.com/search?cat=1005&q={query}",
        profile_pattern=r"^/people/[A-Za-z0-9_-]+/?\Z",
        # Numeric IDs and mutable custom names coexist; no bare-ID shortcut.
    ),
    "tieba": Platform(
        key="tieba",
        name="百度贴吧",
        domains=("tieba.baidu.com",),
        search_url="https://tieba.baidu.com/f/search/res?ie=utf-8&qw={query}",
        # Account identity lives in query parameters, not in a stable path ID.
        profile_pattern=r"^/home/main/?\Z",
    ),
    "csdn": Platform(
        key="csdn",
        name="CSDN",
        domains=("blog.csdn.net",),
        search_url="https://so.csdn.net/so/search?q={query}&t=user",
        profile_pattern=(
            r"^/(?!(?:api|article|articles|community|download|nav|search|"
            r"tags|user|users)/?\Z)[A-Za-z][A-Za-z0-9_-]*/?\Z"
        ),
        id_url="https://blog.csdn.net/{id}",
        id_pattern=(
            r"^(?!(?:api|article|articles|community|download|nav|search|"
            r"tags|user|users)\Z)[A-Za-z][A-Za-z0-9_-]*\Z"
        ),
    ),
    "cnblogs": Platform(
        key="cnblogs",
        name="博客园",
        domains=("cnblogs.com",),
        search_url="https://zzk.cnblogs.com/s/blogpost?w={query}",
        profile_pattern=rf"^/(?!{_CNBLOGS_RESERVED}/?\Z)[A-Za-z0-9_-]+/?\Z",
        id_url="https://www.cnblogs.com/{id}/",
        id_pattern=rf"^(?!{_CNBLOGS_RESERVED}\Z)[A-Za-z0-9_-]+\Z",
    ),
    "jianshu": Platform(
        key="jianshu",
        name="简书",
        domains=("jianshu.com",),
        search_url="https://www.jianshu.com/search?q={query}&type=user",
        profile_pattern=r"^/u/[0-9a-fA-F]{12}/?\Z",
        id_url="https://www.jianshu.com/u/{id}",
        id_pattern=r"^[0-9a-fA-F]{12}\Z",
    ),
    "gitee": Platform(
        key="gitee",
        name="Gitee",
        domains=("gitee.com",),
        # Gitee's public search defaults to repositories.
        search_url="https://search.gitee.com/?q={query}",
        profile_pattern=rf"^/(?!{_GITEE_RESERVED}/?\Z)[A-Za-z0-9][A-Za-z0-9_-]*/?\Z",
        id_url="https://gitee.com/{id}",
        id_pattern=rf"^(?!{_GITEE_RESERVED}\Z)[A-Za-z0-9][A-Za-z0-9_-]*\Z",
        adapter="gitee",
    ),
    "juejin": Platform(
        key="juejin",
        name="稀土掘金",
        domains=("juejin.cn",),
        search_url="https://juejin.cn/search?query={query}",
        profile_pattern=r"^/user/[1-9][0-9]*/?\Z",
        id_url="https://juejin.cn/user/{id}",
        id_pattern=r"^[1-9][0-9]*\Z",
    ),
    "segmentfault": Platform(
        key="segmentfault",
        name="SegmentFault 思否",
        domains=("segmentfault.com",),
        search_url="https://segmentfault.com/search?q={query}",
        profile_pattern=r"^/u/[A-Za-z0-9_-]+/?\Z",
        id_url="https://segmentfault.com/u/{id}",
        id_pattern=r"^[A-Za-z0-9_-]+\Z",
    ),
    "oschina": Platform(
        key="oschina",
        name="开源中国",
        domains=("my.oschina.net",),
        search_url="https://www.oschina.net/search?q={query}",
        profile_pattern=r"^/u/[1-9][0-9]*/?\Z",
        id_url="https://my.oschina.net/u/{id}",
        id_pattern=r"^[1-9][0-9]*\Z",
    ),
    "v2ex": Platform(
        key="v2ex",
        name="V2EX",
        domains=("v2ex.com",),
        search_url="https://www.v2ex.com/search?q={query}",
        profile_pattern=r"^/member/[A-Za-z0-9_]+/?\Z",
        id_url="https://www.v2ex.com/member/{id}",
        id_pattern=r"^[A-Za-z0-9_]+\Z",
    ),
}


__all__ = ["Platform", "PLATFORMS"]

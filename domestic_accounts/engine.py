"""Public API queries and conservative discovery of indexed profile pages.

Only structured platform API responses can produce a `matched` profile.
Search engine hits and successful HTTP responses remain unverified candidates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import html
import re
import unicodedata
from urllib.parse import parse_qs, quote, urlencode, urlsplit
import xml.etree.ElementTree as ET

import requests

from .platforms import Platform


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DomesticAccounts/0.1; public profile lookup)",
    "Accept": "application/json,text/xml,text/html;q=0.8,*/*;q=0.5",
}
STATUS_LABELS = {
    "matched": "接口确认匹配",
    "candidates": "有待核实候选",
    "not_found": "接口未找到",
    "no_candidates": "未发现公开候选",
    "blocked": "访问受限或需登录",
    "error": "查询失败",
    "search_required": "请使用站内搜索",
    "unsupported": "此平台不支持该 ID 格式",
}


@dataclass
class Profile:
    name: str
    account_id: str
    url: str
    source: str
    matched: bool = False
    evidence: str = ""


@dataclass
class Result:
    platform: str
    platform_name: str
    query: str
    mode: str
    status: str
    search_url: str
    profiles: list[Profile] = field(default_factory=list)
    note: str = ""
    total: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class QueryFailure(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def clean_text(value: object) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip()


def normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", clean_text(value)).casefold()


def is_profile_url(url: str, platform: Platform) -> bool:
    """Allow only HTTP(S) profile URLs on the platform's own domains."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        return (
            parts.scheme in {"http", "https"}
            and parts.username is None
            and parts.password is None
            and parts.port in {None, 80, 443}
            and any(host == d or host.endswith("." + d) for d in platform.domains)
            and re.fullmatch(platform.profile_pattern, parts.path) is not None
            and (platform.key != "tieba" or any(parse_qs(parts.query).get(k) for k in ("id", "un")))
        )
    except ValueError:
        return False


class Client:
    def __init__(self, timeout: float = 12):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        # Each query owns its session; cookies never travel between platforms.

    def close(self) -> None:
        self.session.close()

    def get(self, url: str, **kwargs) -> requests.Response:
        try:
            response = self.session.get(url, timeout=self.timeout, **kwargs)
        except requests.Timeout as exc:
            raise QueryFailure("error", "请求超时，请稍后重试或增加 --timeout") from exc
        except requests.RequestException as exc:
            # Do not copy response bodies, cookies, proxy credentials or URLs into errors.
            raise QueryFailure("error", f"网络请求失败（{type(exc).__name__}）") from exc
        if response.status_code in {401, 403, 412, 418, 429}:
            raise QueryFailure("blocked", f"HTTP {response.status_code}：平台限制访问、需要登录或请求过于频繁")
        if response.status_code >= 400 and response.status_code != 404:
            raise QueryFailure("error", f"服务返回 HTTP {response.status_code}")
        return response

    def json(self, url: str, **kwargs):
        response = self.get(url, **kwargs)
        if response.status_code == 404:
            raise QueryFailure("not_found", "公开接口返回 404")
        try:
            return response.json()
        except ValueError as exc:
            raise QueryFailure("blocked", "公开接口未返回 JSON，可能需要登录或遇到验证页面") from exc


def _api_profiles(platform: Platform, query: str, mode: str, client: Client, limit: int):
    if platform.adapter == "bilibili":
        if mode == "id":
            payload = client.json("https://api.bilibili.com/x/web-interface/card", params={"mid": query})
        else:
            payload = client.json(
                "https://api.bilibili.com/x/web-interface/search/type",
                params={"search_type": "bili_user", "keyword": query, "page": 1},
                headers={"Referer": "https://search.bilibili.com/"},
            )
        if not isinstance(payload, dict):
            raise QueryFailure("error", "B站接口数据结构发生变化")
        code = payload.get("code")
        if code != 0:
            if code == -404:
                raise QueryFailure("not_found", "B站接口未找到该账号")
            raise QueryFailure("blocked", f"B站接口返回业务码 {code}，可能需要登录或验证")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise QueryFailure("error", "B站接口缺少账号数据")
        if mode == "id":
            card = data.get("card")
            if not isinstance(card, dict):
                raise QueryFailure("error", "B站接口缺少账号资料")
            rows = [{"mid": card.get("mid"), "uname": card.get("name")}]
            total = 1
        else:
            rows = data.get("result") or []
            total = data.get("numResults")
            if not isinstance(rows, list):
                raise QueryFailure("error", "B站用户列表结构发生变化")
        profiles = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            uid = str(row.get("mid") or "")
            name = clean_text(row.get("uname"))
            if not uid.isascii() or not uid.isdigit() or not name:
                continue
            exact = uid == query if mode == "id" else normalized(name) == normalized(query)
            profiles.append(Profile(name, uid, f"https://space.bilibili.com/{uid}", "bilibili_api", exact,
                                    "公开接口返回 UID 和昵称；" + ("与查询精确匹配" if exact else "平台返回的相关用户")))
        # Put exact nickname matches first, preserving relevance among equal items.
        profiles.sort(key=lambda p: not p.matched)
        return profiles[:limit], total

    if platform.adapter == "gitee":
        if mode == "id":
            payload = client.json(f"https://gitee.com/api/v5/users/{quote(query, safe='')}")
            rows = [payload]
        else:
            payload = client.json("https://gitee.com/api/v5/search/users", params={"q": query, "page": 1, "per_page": limit})
            rows = payload
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise QueryFailure("error", "Gitee 用户接口数据结构发生变化")
        profiles = []
        for row in rows:
            login = str(row.get("login") or "")
            name = clean_text(row.get("name") or login)
            url = str(row.get("html_url") or "")
            if not login or not is_profile_url(url, platform):
                continue
            exact = normalized(login) == normalized(query)
            if mode != "id":
                exact = exact or normalized(name) == normalized(query)
            profiles.append(Profile(name, login, url, "gitee_api", exact,
                                    "公开接口返回账号和昵称；" + ("与查询精确匹配" if exact else "平台返回的相关用户")))
        profiles.sort(key=lambda p: not p.matched)
        return profiles[:limit], None
    raise QueryFailure("error", "平台没有配置公开接口")


def _indexed_profiles(platform: Platform, query: str, client: Client, limit: int) -> list[Profile]:
    # Remove search operator punctuation from user text and keep the phrase quoted.
    phrase = query.replace('"', ' ').replace('\\', ' ').strip()
    sites = " OR ".join(f"site:{domain}" for domain in platform.domains)
    response = client.get("https://www.bing.com/search", params={"q": f'"{phrase}" ({sites})', "format": "rss"})
    if response.status_code == 404:
        raise QueryFailure("error", "公开搜索服务不可用")
    body = response.content
    if len(body) > 2_000_000 or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise QueryFailure("error", "搜索服务返回了不支持的内容")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise QueryFailure("blocked", "公开搜索服务未返回 RSS，可能出现验证页面") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise QueryFailure("error", "公开搜索服务响应结构发生变化")
    profiles = []
    seen = set()
    for item in root.findall("./channel/item"):
        url = (item.findtext("link") or "").strip()
        if not is_profile_url(url, platform):
            continue
        # Keep access tokens (e.g. Xiaohongshu) in links; deduplicate by identity.
        parts = urlsplit(url)
        canonical = f"{parts.scheme}://{parts.netloc}{parts.path}"
        identity = canonical.rstrip("/")
        if platform.key == "tieba":
            params = parse_qs(parts.query)
            identity += "?" + urlencode({k: params[k][0] for k in ("id", "un") if params.get(k)})
        if parts.query:
            canonical += "?" + parts.query
        if identity in seen:
            continue
        title = clean_text(item.findtext("title"))
        snippet = clean_text(item.findtext("description"))
        if normalized(query) not in normalized(title + " " + snippet):
            continue
        seen.add(identity)
        profiles.append(Profile(title, "", canonical, "bing_index", False,
                                "搜索引擎收录的个人主页，摘要含查询词；尚未验证主页当前昵称"))
        if len(profiles) >= limit:
            break
    return profiles


def _id_profile(platform: Platform, query: str, client: Client) -> list[Profile]:
    url = platform.id_url.format(id=quote(query, safe=""))
    response = client.get(url)
    if response.status_code == 404:
        raise QueryFailure("not_found", "该账号地址返回 404；这不排除平台访问限制导致的错误响应")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text[:500_000], re.I | re.S)
    title = clean_text(title_match.group(1)) if title_match else ""
    suspicious = ("登录", "安全验证", "访问验证", "验证码", "access denied", "just a moment", "security verification", "sign in")
    if any(token in title.casefold() for token in suspicious):
        raise QueryFailure("blocked", "返回登录或验证页面，请在浏览器打开平台入口")
    # A generic landing page or redirected different account is never a match.
    if not is_profile_url(response.url, platform) or urlsplit(response.url).path.rstrip("/").casefold() != urlsplit(url).path.rstrip("/").casefold():
        raise QueryFailure("search_required", "请求跳转到了其他页面，无法确认该 ID；请手动核实")
    if response.status_code != 200:
        raise QueryFailure("error", f"账号页面返回 HTTP {response.status_code}")
    return [Profile(title or query, query, url, "profile_page", False,
                    "账号地址返回 HTTP 200；未通过结构化资料确认，仍需手动核实")]


def query_platform(platform: Platform, query: str, mode: str = "nickname", *, timeout: float = 12,
                   limit: int = 5, web_search: bool = True) -> Result:
    result = Result(platform.key, platform.name, query, mode, "error",
                    platform.search_url.format(query=quote(query, safe="")))
    if mode == "id" and (not platform.id_url or not platform.id_pattern or re.fullmatch(platform.id_pattern, query) is None):
        result.status = "unsupported"
        result.note = "请使用该平台的主页 ID，而非显示昵称；可改用 --mode nickname"
        return result
    client = Client(timeout)
    try:
        if platform.adapter in {"bilibili", "gitee"}:
            try:
                result.profiles, result.total = _api_profiles(platform, query, mode, client, limit)
                result.status = "matched" if any(p.matched for p in result.profiles) else "candidates" if result.profiles else "not_found"
                result.note = "公开接口返回的匹配仅说明账号名或昵称相同，不能证明属于同一个人。"
                if mode == "nickname":
                    result.note += "仅查询第一页；相关用户可能同名，结果并非全量。"
                return result
            except QueryFailure as exc:
                if mode == "id" or not web_search or exc.status == "not_found":
                    raise
                api_note = str(exc)
                # API failure falls back to public index candidates, never confirmed matches.
                try:
                    result.profiles = _indexed_profiles(platform, query, client, limit)
                except QueryFailure as fallback:
                    result.status = exc.status
                    result.note = f"{api_note}；备用公开检索：{fallback}。可打开站内搜索入口。"
                    return result
                result.status = "candidates" if result.profiles else exc.status
                result.note = f"{api_note}；已尝试公开索引备用检索，接口匹配未完成。"
                return result
        if mode == "id":
            result.profiles = _id_profile(platform, query, client)
            result.status = "candidates"
            result.note = "HTTP 200 不能单独证明账号存在或身份匹配，请打开主页核实。"
        elif web_search:
            result.profiles = _indexed_profiles(platform, query, client, limit)
            result.status = "candidates" if result.profiles else "no_candidates"
            result.note = "检索公开收录的用户主页；未收录、登录后可见或新账号可能查不到，可继续使用站内搜索入口。"
        else:
            result.status = "search_required"
            result.note = "该平台未配置公开用户搜索接口；已生成站内搜索入口。"
    except QueryFailure as exc:
        result.status = exc.status
        result.note = str(exc)
    finally:
        client.close()
    return result


def indexed_search_url(platform: Platform, query: str) -> str:
    return "https://www.bing.com/search?" + urlencode({"q": f'"{query}" site:{platform.domains[0]}'})

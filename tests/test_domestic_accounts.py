"""Conservative account discovery boundaries; all network traffic is mocked."""
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from domestic_accounts.engine import Client, QueryFailure, query_platform
from domestic_accounts.platforms import PLATFORMS


def response(body="", *, status=200, url="https://www.bing.com/search"):
    result = Mock(status_code=status, url=url, text=body)
    result.content = body.encode("utf-8")
    return result


def rss(*items):
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    for title, url, description in items:
        item = ET.SubElement(channel, "item")
        for key, value in (("title", title), ("link", url), ("description", description)):
            ET.SubElement(item, key).text = value
    return ET.tostring(root, encoding="unicode")


class DomesticAccountsTests(unittest.TestCase):
    def setUp(self):
        # A missed mock fails locally instead of making a real HTTP request.
        network = patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network request"))
        network.start()
        self.addCleanup(network.stop)

    def query(self, platform, query="Alice", **kwargs):
        return query_platform(PLATFORMS[platform], query, **kwargs)

    def assert_unconfirmed(self, result, status=None):
        if status is not None:
            self.assertEqual(result.status, status)
        self.assertNotEqual(result.status, "matched")
        self.assertTrue(all(not profile.matched for profile in result.profiles))

    def test_http_200_profile_page_is_only_a_candidate(self):
        url = "https://www.zhihu.com/people/alice"
        with patch.object(Client, "get", return_value=response("<title>Alice</title>", url=url)):
            result = self.query("zhihu", "alice", mode="id")
        self.assert_unconfirmed(result, "candidates")
        self.assertEqual(len(result.profiles), 1)
        self.assertIn("200", result.note)

    def test_login_and_antibot_pages_are_blocked(self):
        for title in ("登录", "安全验证", "验证码", "Access Denied", "Just a moment", "Sign in"):
            with self.subTest(title=title), patch.object(Client, "get", return_value=response(
                    f"<title>{title}</title>", url="https://www.zhihu.com/people/alice")):
                result = self.query("zhihu", "alice", mode="id")
                self.assert_unconfirmed(result, "blocked")
                self.assertEqual(result.profiles, [])

    def test_page_404_and_server_error_are_not_candidates(self):
        for status, expected in ((404, "not_found"), (500, "error")):
            with self.subTest(status=status), patch.object(Client, "get", return_value=response(
                    "<title>Alice</title>", status=status, url="https://www.zhihu.com/people/alice")):
                result = self.query("zhihu", "alice", mode="id")
                self.assert_unconfirmed(result, expected)
                self.assertEqual(result.profiles, [])

    def test_redirect_to_homepage_or_another_account_is_unconfirmed(self):
        for url in ("https://www.zhihu.com/", "https://www.zhihu.com/people/bob",
                    "https://www.zhihu.com.evil.test/people/alice"):
            with self.subTest(url=url), patch.object(Client, "get", return_value=response("<title>Alice</title>", url=url)):
                self.assert_unconfirmed(self.query("zhihu", "alice", mode="id"), "search_required")

    def test_invalid_ids_do_not_create_client_or_request_network(self):
        cases = (("bilibili", "0"), ("bilibili", "１２３"), ("weibo", "-1"),
                 ("zhihu", "alice/bob"), ("zhihu", "https://zhihu.com/people/alice"),
                 ("gitee", "search"), ("xiaohongshu", "123"), ("douyin", "alice"),
                 ("jianshu", "not-a-hex-id"), ("douban", "alice"), ("kuaishou", "alice"))
        with patch("domestic_accounts.engine.Client") as client:
            for platform, value in cases:
                with self.subTest(platform=platform, value=value):
                    self.assert_unconfirmed(self.query(platform, value, mode="id"), "unsupported")
            client.assert_not_called()

    def test_bilibili_exact_nickname_precedes_related_users_before_limit(self):
        payload = {"code": 0, "data": {"numResults": 3, "result": [
            {"mid": 1, "uname": "Alice fan"}, {"mid": 2, "uname": "<em>ＡＬＩＣＥ</em>"},
            {"mid": 3, "uname": "Bob"}]}}
        with patch.object(Client, "json", return_value=payload):
            result = self.query("bilibili", limit=1)
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.total, 3)
        self.assertEqual([p.account_id for p in result.profiles], ["2"])
        self.assertTrue(result.profiles[0].matched)

    def test_bilibili_related_nickname_is_only_a_candidate(self):
        payload = {"code": 0, "data": {"result": [{"mid": 1, "uname": "Alice fan"}]}}
        with patch.object(Client, "json", return_value=payload):
            self.assert_unconfirmed(self.query("bilibili"), "candidates")

    def test_bilibili_id_must_match_returned_uid(self):
        for uid, expected in (("123", "matched"), ("456", "candidates")):
            with self.subTest(uid=uid), patch.object(Client, "json", return_value={
                    "code": 0, "data": {"card": {"mid": uid, "name": "Alice"}}}):
                result = self.query("bilibili", "123", mode="id")
                self.assertEqual(result.status, expected)
                self.assertEqual(result.profiles[0].matched, uid == "123")

    def test_bilibili_business_errors_and_malformed_data_are_not_matches(self):
        cases = (({"code": -404}, "not_found"), ({"code": -412}, "blocked"),
                 ({"code": 0, "data": None}, "error"), ([], "error"),
                 ({"code": 0, "data": {"result": "unexpected"}}, "error"))
        for payload, expected in cases:
            with self.subTest(payload=payload), patch.object(Client, "json", return_value=payload):
                result = self.query("bilibili", web_search=False)
                self.assert_unconfirmed(result, expected)
                self.assertEqual(result.profiles, [])

    def test_bilibili_malformed_rows_cannot_create_profiles(self):
        payload = {"code": 0, "data": {"result": [None, "Alice", {"uname": "Alice"},
                   {"mid": "１２３", "uname": "Alice"}, {"mid": 123, "uname": ""}]}}
        with patch.object(Client, "json", return_value=payload):
            result = self.query("bilibili")
        self.assert_unconfirmed(result, "not_found")
        self.assertEqual(result.profiles, [])

    def test_gitee_login_or_display_name_can_match_nickname(self):
        for login, name in (("alice", "Someone"), ("another-user", "ＡＬＩＣＥ")):
            with self.subTest(login=login), patch.object(Client, "json", return_value=[
                    {"login": login, "name": name, "html_url": f"https://gitee.com/{login}"}]):
                result = self.query("gitee")
                self.assertEqual(result.status, "matched")
                self.assertTrue(result.profiles[0].matched)

    def test_gitee_display_name_does_not_confirm_different_id(self):
        with patch.object(Client, "json", return_value={
                "login": "other", "name": "alice", "html_url": "https://gitee.com/other"}):
            self.assert_unconfirmed(self.query("gitee", "alice", mode="id"), "candidates")

    def test_gitee_rejects_fake_domain_and_repository_urls(self):
        urls = ("https://gitee.com.evil.test/alice", "https://evilgitee.com/alice",
                "https://gitee.com/alice/repository", "https://gitee.com/search")
        with patch.object(Client, "json", return_value=[
                {"login": "alice", "name": "Alice", "html_url": url} for url in urls]):
            result = self.query("gitee")
        self.assert_unconfirmed(result, "not_found")
        self.assertEqual(result.profiles, [])

    def test_rss_filters_domains_articles_missing_nickname_and_deduplicates(self):
        body = rss(
            ("Alice", "https://evil.test/people/alice", ""),
            ("Alice", "https://www.zhihu.com.evil.test/people/alice", ""),
            ("Alice", "https://evilzhihu.com/people/alice", ""),
            ("Alice", "https://www.zhihu.com/question/123/answer/456", ""),
            ("Bob", "https://www.zhihu.com/people/bob", "nothing relevant"),
            ("Alice", "https://www.zhihu.com/people/alice?utm_source=test", ""),
            ("Alice again", "https://www.zhihu.com/people/alice#top", ""),
            ("Someone", "https://www.zhihu.com/people/another", "ＡＬＩＣＥ 的主页"))
        with patch.object(Client, "get", return_value=response(body)):
            result = self.query("zhihu")
        self.assert_unconfirmed(result, "candidates")
        self.assertEqual([p.url for p in result.profiles], [
            "https://www.zhihu.com/people/alice?utm_source=test", "https://www.zhihu.com/people/another"])

    def test_rss_rejects_credentials_non_http_and_unexpected_ports(self):
        urls = ("https://evil.test@www.zhihu.com/people/alice",
                "https://www.zhihu.com:444/people/alice", "ftp://www.zhihu.com/people/alice",
                "https://www.zhihu.com:invalid/people/alice")
        with patch.object(Client, "get", return_value=response(rss(*[("Alice", u, "") for u in urls]))):
            result = self.query("zhihu")
        self.assert_unconfirmed(result, "no_candidates")
        self.assertEqual(result.profiles, [])

    def test_rss_limit_is_applied_after_filtering(self):
        body = rss(("Bob", "https://www.zhihu.com/people/bob", ""),
                   ("Alice", "https://www.zhihu.com/people/one", ""),
                   ("Alice", "https://www.zhihu.com/people/two", ""))
        with patch.object(Client, "get", return_value=response(body)):
            result = self.query("zhihu", limit=1)
        self.assertEqual([p.url for p in result.profiles], ["https://www.zhihu.com/people/one"])

    def test_rss_keeps_tieba_account_identity_in_query_parameters(self):
        first = "https://tieba.baidu.com/home/main?un=Alice"
        second = "https://tieba.baidu.com/home/main?un=Alice2"
        with patch.object(Client, "get", return_value=response(rss(
                ("Alice", first, ""), ("Alice2", second, "")))):
            result = self.query("tieba")
        self.assert_unconfirmed(result, "candidates")
        self.assertEqual([p.url for p in result.profiles], [first, second])

    def test_rss_rejects_tieba_entry_without_account_identity(self):
        urls = ("https://tieba.baidu.com/home/main", "https://tieba.baidu.com/home/main?un=",
                "https://tieba.baidu.com/home/main?tracking=Alice")
        with patch.object(Client, "get", return_value=response(rss(*[("Alice", u, "") for u in urls]))):
            result = self.query("tieba")
        self.assert_unconfirmed(result, "no_candidates")
        self.assertEqual(result.profiles, [])

    def test_rss_preserves_xiaohongshu_access_token(self):
        url = "https://www.xiaohongshu.com/user/profile/0123456789abcdef01234567?xsec_token=access-token&xsec_source=pc_search"
        with patch.object(Client, "get", return_value=response(rss(("Alice", url, "")))):
            result = self.query("xiaohongshu")
        self.assert_unconfirmed(result, "candidates")
        self.assertEqual([p.url for p in result.profiles], [url])

    def test_bad_xml_and_wrong_rss_structure_fail_safely(self):
        for body, expected in (("<rss><channel>", "blocked"), ("<html>captcha</html>", "error"),
                               ("<rss/>", "error")):
            with self.subTest(body=body), patch.object(Client, "get", return_value=response(body)):
                result = self.query("zhihu")
                self.assert_unconfirmed(result, expected)
                self.assertEqual(result.profiles, [])

    def test_doctype_and_entity_are_rejected_before_xml_parsing(self):
        for body in ('<!DOCTYPE rss [<!ENTITY x "Alice">]><rss><channel/></rss>',
                     '<!doctype rss SYSTEM "file:///etc/passwd"><rss><channel/></rss>',
                     '<!ENTITY x "Alice"><rss><channel/></rss>'):
            with self.subTest(body=body), patch.object(Client, "get", return_value=response(body)), \
                    patch("domestic_accounts.engine.ET.fromstring") as parse:
                result = self.query("zhihu")
                self.assert_unconfirmed(result, "error")
                parse.assert_not_called()

    def test_oversized_rss_is_rejected_before_parsing(self):
        with patch.object(Client, "get", return_value=response(" " * 2_000_001)), \
                patch("domestic_accounts.engine.ET.fromstring") as parse:
            self.assert_unconfirmed(self.query("zhihu"), "error")
            parse.assert_not_called()

    def test_api_failure_falls_back_only_to_unconfirmed_search_results(self):
        body = rss(("Alice", "https://space.bilibili.com/123", ""))
        with patch.object(Client, "json", side_effect=QueryFailure("blocked", "HTTP 403")), \
                patch.object(Client, "get", return_value=response(body)):
            result = self.query("bilibili")
        self.assert_unconfirmed(result, "candidates")
        self.assertEqual(result.profiles[0].source, "bing_index")
        self.assertIn("403", result.note)

    def test_empty_or_failed_fallback_preserves_api_failure_status(self):
        for fallback in (response(rss()), QueryFailure("error", "搜索失败")):
            with self.subTest(fallback=fallback):
                kwargs = {"side_effect": fallback} if isinstance(fallback, Exception) else {"return_value": fallback}
                with patch.object(Client, "json", side_effect=QueryFailure("blocked", "HTTP 429")), \
                        patch.object(Client, "get", **kwargs):
                    result = self.query("gitee")
                self.assert_unconfirmed(result, "blocked")
                self.assertEqual(result.profiles, [])
                self.assertIn("429", result.note)

    def test_api_not_found_or_id_failure_does_not_search_fallback(self):
        for mode, status in (("nickname", "not_found"), ("id", "blocked")):
            with self.subTest(mode=mode), patch.object(Client, "json", side_effect=QueryFailure(status, "接口失败")), \
                    patch.object(Client, "get") as get:
                result = self.query("bilibili", "123", mode=mode)
                self.assert_unconfirmed(result, status)
                get.assert_not_called()

    def test_http_200_non_json_api_page_is_blocked(self):
        page = response("<html><title>安全验证</title></html>")
        page.json.side_effect = ValueError("not JSON")
        with patch.object(Client, "get", return_value=page):
            self.assert_unconfirmed(self.query("gitee", web_search=False), "blocked")

    def test_disabling_search_for_web_platform_sends_no_request(self):
        with patch.object(Client, "get") as get, patch.object(Client, "json") as json:
            self.assert_unconfirmed(self.query("zhihu", web_search=False), "search_required")
            get.assert_not_called()
            json.assert_not_called()


if __name__ == "__main__":
    unittest.main()

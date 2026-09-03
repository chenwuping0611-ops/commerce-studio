import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests


AMAZON_HOST_PATTERN = re.compile(
    r"(^|\.)amazon\.(?:com|ca|co\.uk|de|es|fr|it|nl|pl|se|com\.au|"
    r"com\.be|com\.br|com\.mx|co\.jp|in|sg|ae|sa|tr)$",
    re.IGNORECASE,
)
AMAZON_ASIN_PATTERN = re.compile(
    r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?#]|$)",
    re.IGNORECASE,
)

MAX_PAGE_BYTES = 240000
MAX_URLS = 10


class _VisibleTextParser(HTMLParser):
    """Extract readable HTML text while preserving useful block boundaries."""

    _ignored_tags = {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "nav",
        "footer",
    }
    _block_tags = {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._line_parts = []
        self.parts = []
        self.title_parts = []
        self.in_title = False

    def _flush(self):
        value = re.sub(r"\s+", " ", " ".join(self._line_parts)).strip()
        self._line_parts = []
        if value and (not self.parts or self.parts[-1] != value):
            self.parts.append(value)

    def handle_starttag(self, tag, attrs):
        tag = str(tag or "").lower()
        if tag in self._ignored_tags:
            self._flush()
            self._ignored_depth += 1
            return
        if tag == "title":
            self.in_title = True
        if tag in self._block_tags:
            self._flush()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = str(tag or "").lower()
        if tag == "title":
            self.in_title = False
        if tag in self._ignored_tags:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if tag in self._block_tags:
            self._flush()

    def handle_data(self, data):
        if self._ignored_depth:
            return
        value = re.sub(r"\s+", " ", str(data or "")).strip()
        if not value:
            return
        if self.in_title:
            self.title_parts.append(value)
        self._line_parts.append(value)

    def close(self):
        super().close()
        self._flush()


def _normalise_url(value):
    value = str(value or "").strip().strip('<>"\' ')
    if not value:
        return ""
    if value.lower().startswith("http://"):
        return "https://" + value[7:]
    if not value.lower().startswith(("https://", "http://")):
        return "https://" + value
    return value


def _is_allowed_amazon_url(url):
    parsed = urlparse(str(url or "").strip())
    return (
        parsed.scheme.lower() == "https"
        and bool(parsed.hostname)
        and bool(AMAZON_HOST_PATTERN.search(parsed.hostname.lower()))
    )


def _canonical_url(url):
    value = _normalise_url(url)
    parsed = urlparse(value)
    match = AMAZON_ASIN_PATTERN.search(parsed.path or "")
    if not match or not parsed.hostname:
        return value
    return f"https://{parsed.hostname.lower()}/dp/{match.group(1).upper()}"


def _markdown_from_html(raw, source_url):
    parser = _VisibleTextParser()
    parser.feed(raw)
    parser.close()
    title = " ".join(parser.title_parts).strip()
    lines = ["# Amazon 商品页面"]
    if title:
        lines.extend(["", "## 页面标题", title])
    lines.extend(["", "## 页面可见文本"])
    lines.extend(f"- {item}" for item in parser.parts if item)
    lines.extend(["", f"> 页面来源：{source_url}"])
    return "\n".join(lines).strip()


def _fetch_page(session, url, maximum):
    response = None
    try:
        response = session.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=(10, 30),
            allow_redirects=True,
        )
        response.raise_for_status()
        raw = getattr(response, "content", b"") or b""
        if not raw:
            raw = str(getattr(response, "text", "") or "").encode("utf-8")
        raw = raw[: maximum * 2]
        encoding = (
            getattr(response, "encoding", None)
            or getattr(response, "apparent_encoding", None)
            or "utf-8"
        )
        decoded = raw.decode(encoding, errors="replace")
        return _limit_utf8(_markdown_from_html(decoded, url), maximum)
    finally:
        if response is not None:
            response.close()


def _limit_utf8(value, maximum):
    encoded = str(value or "").encode("utf-8")
    if len(encoded) <= maximum:
        return str(value or "")
    return encoded[:maximum].decode("utf-8", errors="ignore").rstrip()


def fetch_competitor_pages(urls):
    """Read a bounded amount of static visible text for compatibility callers."""

    unique_urls = []
    for raw_url in urls or []:
        url = _normalise_url(raw_url)
        if url and url not in unique_urls:
            unique_urls.append(url)
    unique_urls = unique_urls[:MAX_URLS]
    if not unique_urls:
        return ""

    blocks = []
    with requests.Session() as session:
        for index, original_url in enumerate(unique_urls, start=1):
            label = chr(64 + index) if index <= 26 else str(index)
            fetch_url = _canonical_url(original_url)
            block = [
                f"# 竞品 {label}",
                "",
                f"- 用户提交链接：{original_url}",
            ]
            if not _is_allowed_amazon_url(original_url):
                block.extend(
                    [
                        "",
                        "## 页面获取状态",
                        "信息缺失：只允许 HTTPS Amazon 商品链接。",
                    ]
                )
            else:
                try:
                    markdown = _fetch_page(session, fetch_url, MAX_PAGE_BYTES)
                    block.extend(["", markdown])
                except Exception as exc:
                    block.extend(
                        [
                            "",
                            "## 页面获取状态",
                            "信息缺失：页面读取失败。",
                            f"读取错误：{exc}",
                        ]
                    )
            blocks.append("\n".join(block).strip())
    return "\n\n---\n\n".join(blocks)

"""Web pages: fetch a URL, then keep the main text and drop the page furniture.

The extractor follows the idea of Readability-style tools with the standard
library only: use the page's <article> or <main> element when it has one,
otherwise the element whose paragraphs hold the most text; inside it, drop
navigation, forms, scripts, and blocks whose class or ID names them as
menus, sidebars, comments, or adverts. A web page has no pages, so its text
is one page (locator p1).
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from html.parser import HTMLParser

from groundcast.ingest.units import ExtractionError, Unit, table_text
from groundcast.models import utc_now

_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
# Elements never part of the main text.
_DROP = frozenset(
    {
        "script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "form", "button",
        "select", "textarea", "nav", "aside", "footer", "dialog", "head", "math",
    }
)  # fmt: skip
_BLOCK = frozenset(
    {
        "address", "article", "blockquote", "dd", "div", "dl", "dt", "figcaption", "figure", "h1", "h2", "h3",
        "h4", "h5", "h6", "header", "hr", "li", "main", "ol", "p", "pre", "section", "table", "tbody", "td",
        "tfoot", "th", "thead", "tr", "ul", "br", "caption", "details", "summary",
    }
)  # fmt: skip
# Closing any of these ends an open <p> or <li>, as browsers do.
_AUTO_CLOSE = {"p": _BLOCK - {"br", "hr"}, "li": frozenset({"li"}), "dt": frozenset({"dt", "dd"}),
               "dd": frozenset({"dt", "dd"}), "tr": frozenset({"tr"}), "td": frozenset({"td", "th", "tr"}),
               "th": frozenset({"td", "th", "tr"})}  # fmt: skip
_BOILERPLATE = re.compile(
    r"(^|[\s_-])(nav|navbar|menu|breadcrumbs?|footer|sidebar|comments?|share|social|cookies?|banner|ads?|advert"
    r"\w*|promo\w*|related|newsletter|subscribe|signup|skip|popup|modal|masthead|toolbar|pagination)($|[\s_-])",
    re.IGNORECASE,
)
# A class or ID that also names content keeps its element.
_CONTENT = re.compile(r"article|content|main|body|entry|post|story|text", re.IGNORECASE)
_BOILERPLATE_ROLES = frozenset({"navigation", "banner", "contentinfo", "complementary", "search", "dialog"})
_SPACES = re.compile(r"\s+")
_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w-]+)""", re.IGNORECASE)


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list[Node | str] = field(default_factory=list)
    parent: Node | None = None


class _TreeBuilder(HTMLParser):
    """A forgiving DOM: enough structure to find the main text of real pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.current = self.root

    def _open_ancestor(self, tags: frozenset[str] | set[str]) -> Node | None:
        node: Node | None = self.current
        while node is not None and node is not self.root:
            if node.tag in tags:
                return node
            node = node.parent
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        while tag in _AUTO_CLOSE.get(self.current.tag, ()):
            self.current = self.current.parent or self.root
        node = Node(tag, {k: v or "" for k, v in attrs}, parent=self.current)
        self.current.children.append(node)
        if tag not in _VOID:
            self.current = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.current.children.append(Node(tag, {k: v or "" for k, v in attrs}, parent=self.current))

    def handle_endtag(self, tag: str) -> None:
        node = self._open_ancestor({tag})
        if node is not None:
            self.current = node.parent or self.root

    def handle_data(self, data: str) -> None:
        self.current.children.append(data)


def _elements(node: Node) -> list[Node]:
    out = []
    for child in node.children:
        if isinstance(child, Node):
            out.append(child)
            out.extend(_elements(child))
    return out


def _text(node: Node) -> str:
    return "".join(c if isinstance(c, str) else _text(c) for c in node.children)


def _is_furniture(node: Node) -> bool:
    if node.tag in _DROP or "hidden" in node.attrs or node.attrs.get("aria-hidden") == "true":
        return True
    if node.attrs.get("role", "") in _BOILERPLATE_ROLES:
        return True
    names = f"{node.attrs.get('class', '')} {node.attrs.get('id', '')}"
    if node.tag in ("article", "main", "body") or _CONTENT.search(names):
        return False
    return bool(_BOILERPLATE.search(names))


def _main_container(root: Node) -> Node:
    elements = _elements(root)
    for tag in ("article", "main"):
        found = [n for n in elements if n.tag == tag]
        if found:
            return max(found, key=lambda n: len(_text(n)))
    found = [n for n in elements if n.attrs.get("role") == "main"]
    if found:
        return found[0]
    # Score each element by the paragraph text directly inside it.
    scores: dict[int, tuple[float, Node]] = {}
    for p in (n for n in elements if n.tag == "p"):
        length = len(_SPACES.sub(" ", _text(p)).strip())
        if length < 25:
            continue
        for parent, weight in ((p.parent, 1.0), (p.parent.parent if p.parent else None, 0.5)):
            if parent is not None:
                old = scores.get(id(parent), (0.0, parent))[0]
                scores[id(parent)] = (old + length * weight, parent)
    if scores:
        return max(scores.values(), key=lambda s: s[0])[1]
    body = next((n for n in elements if n.tag == "body"), None)
    return body or root


def _blocks(container: Node) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        text = _SPACES.sub(" ", "".join(current)).strip()
        if text:
            blocks.append(text)
        current.clear()

    def visit(node: Node) -> None:
        for child in node.children:
            if isinstance(child, str):
                current.append(child)
                continue
            if _is_furniture(child):
                continue
            if child.tag == "table":
                flush()
                rows = [[_text(c) for c in tr.children if isinstance(c, Node) and c.tag in ("td", "th")]
                        for tr in _elements(child) if tr.tag == "tr"]  # fmt: skip
                text = table_text(rows)
                if text:
                    blocks.append(text)
                continue
            if child.tag in _BLOCK:
                flush()
                visit(child)
                flush()
            else:
                visit(child)

    visit(container)
    flush()
    return blocks


def page_title(root: Node) -> str:
    elements = _elements(root)
    for n in elements:
        if n.tag == "meta" and n.attrs.get("property") == "og:title" and n.attrs.get("content"):
            return _SPACES.sub(" ", n.attrs["content"]).strip()
    for tag in ("title", "h1"):
        n = next((e for e in elements if e.tag == tag), None)
        if n is not None and _text(n).strip():
            return _SPACES.sub(" ", _text(n)).strip()
    return ""


def parse_html(html: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def html_units(html: str) -> list[Unit]:
    return [Unit("p1", _blocks(_main_container(parse_html(html))))]


def decode_html(data: bytes, header_charset: str | None = None) -> str:
    """Decode with the HTTP charset, else the page's meta charset, else UTF-8."""
    for charset in (header_charset, _meta_charset(data), "utf-8"):
        if not charset:
            continue
        try:
            return data.decode(charset, errors="replace")
        except LookupError:
            continue
    return data.decode("utf-8", errors="replace")


def _meta_charset(data: bytes) -> str | None:
    match = _CHARSET.search(data[:4096])
    return match.group(1).decode("ascii", errors="ignore") if match else None


@dataclass
class Fetched:
    url: str  # after redirects
    data: bytes
    content_type: str  # media type without parameters
    charset: str | None
    fetched_at: datetime


def fetch(url: str, timeout_s: float, max_bytes: int, user_agent: str) -> Fetched:
    """Download a page; only http and https, and at most max_bytes."""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ExtractionError("only http and https addresses can be fetched")
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 (scheme checked above)
            data = response.read(max_bytes + 1)
            headers: Message = response.headers
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        raise ExtractionError(f"the server answered {exc.code} {exc.reason} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ExtractionError(f"could not fetch {url}: {exc}") from exc
    if len(data) > max_bytes:
        raise ExtractionError(f"{url} is larger than {max_bytes} bytes (ingest.fetch_max_bytes)")
    return Fetched(final_url, data, headers.get_content_type(), headers.get_content_charset(), utc_now())

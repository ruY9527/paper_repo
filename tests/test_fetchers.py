"""Phase 2 验收：respx Mock 三个数据源，验证解析完整性与 venue 过滤。"""

from datetime import date

import httpx
import respx

from paperflow.config import load_example_config
from paperflow.fetchers.arxiv_fetcher import ArxivFetcher
from paperflow.fetchers.base import RateLimiter
from paperflow.fetchers.openalex_fetcher import OpenAlexFetcher, reconstruct_abstract
from paperflow.fetchers.openreview_fetcher import OpenReviewFetcher
from paperflow.fetchers.single_adder import SinglePaperAdder

CONFIG = load_example_config()
START, END = date(2026, 3, 1), date(2026, 3, 2)

ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2603.12345v1</id>
    <title>  Action Recognition with Vision Language Models  </title>
    <summary>We propose a novel method for video understanding.</summary>
    <author><name>Alice Zhang</name></author>
    <author><name>Bob Li</name></author>
    <published>2026-03-01T10:00:00Z</published>
    <arxiv:comment>Accepted to CVPR 2026. Oral.</arxiv:comment>
    <arxiv:journal_ref></arxiv:journal_ref>
    <link href="http://arxiv.org/pdf/2603.12345v1" title="pdf" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2603.99999v1</id>
    <title>A Random Unrelated Preprint</title>
    <summary>No target venue here.</summary>
    <author><name>Some One</name></author>
    <published>2026-03-02T10:00:00Z</published>
    <arxiv:comment>Just a preprint.</arxiv:comment>
  </entry>
</feed>
"""

OPENALEX_JSON = {
    "results": [
        {
            "id": "https://openalex.org/W123",
            "title": "TPAMI Journal Paper on Video Understanding",
            "display_name": "TPAMI Journal Paper on Video Understanding",
            "publication_year": 2026,
            "publication_date": "2026-03-01",
            "doi": "https://doi.org/10.1109/TPAMI.2026.111",
            "primary_location": {
                "source": {"display_name": "IEEE Transactions on Pattern Analysis and Machine Intelligence",
                           "issn": ["0162-8828", "1939-3539"]},
                "landing_page_url": "https://ieeexplore.ieee.org/document/111",
                "pdf_url": "https://example.com/paper.pdf",
            },
            "open_access": {"oa_url": "https://example.com/oa"},
            "best_oa_location": {"pdf_url": "https://example.com/paper.pdf"},
            "authorships": [
                {"author": {"display_name": "Kaiming He"},
                 "institutions": [{"display_name": "Google DeepMind"}]},
            ],
            "abstract_inverted_index": {
                "We": [0], "propose": [1], "a": [2], "novel": [3], "method": [4],
            },
            "locations": [{"landing_page_url": "https://github.com/foo/bar"}],
            "ids": {"doi": "https://doi.org/10.1109/TPAMI.2026.111"},
        }
    ],
    "meta": {"next_cursor": None},
}

OPENREVIEW_JSON = {
    "notes": [
        {
            "id": "note1", "forum": "note1", "tcdate": 1772400000000,
            "content": {
                "title": {"value": "ICLR 2026 Spotlight Paper"},
                "authors": {"value": ["Alice", "Bob"]},
                "abstract": {"value": "An ICLR spotlight abstract."},
                "venue": {"value": "ICLR 2026 Spotlight"},
                "venueid": {"value": "ICLR.cc/2026/Conference"},
            },
        },
        {
            "id": "note2", "forum": "note2",
            "content": {
                "title": {"value": "Rejected Paper"},
                "venueid": {"value": "ICLR.cc/2026/Conference/Rejected"},
            },
        },
    ]
}


def _client() -> httpx.Client:
    # trust_env=False 避免 respx 与系统代理环境变量（IPv6 地址）冲突
    return httpx.Client(timeout=30.0, follow_redirects=True, trust_env=False)


def test_reconstruct_abstract():
    assert reconstruct_abstract({"a": [0, 2], "b": [1]}) == "a b a"
    assert reconstruct_abstract(None) == ""


def test_arxiv_parse_and_filter(monkeypatch):
    # monkeypatch sleep 避免限流等待
    monkeypatch.setattr("paperflow.fetchers.base.time.sleep", lambda *_: None)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(200, text=ARXIV_XML)
        )
        fetcher = ArxivFetcher(CONFIG, client=_client())
        papers = fetcher.fetch_by_date_range(START, END)
    assert len(papers) == 1  # 普通预印本被过滤
    p = papers[0]
    assert p.venue == "CVPR"
    assert p.title == "Action Recognition with Vision Language Models"
    assert p.authors == ["Alice Zhang", "Bob Li"]
    assert p.arxiv_id == "2603.12345v1"
    assert p.pdf_url == "http://arxiv.org/pdf/2603.12345v1"
    assert "Oral" in p.comment


def test_arxiv_venue_filter(monkeypatch):
    monkeypatch.setattr("paperflow.fetchers.base.time.sleep", lambda *_: None)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(200, text=ARXIV_XML)
        )
        fetcher = ArxivFetcher(CONFIG, client=_client())
        papers = fetcher.fetch_by_date_range(START, END, venues=["NEURIPS"])
    assert papers == []


def test_openalex_parse(monkeypatch):
    monkeypatch.setattr("paperflow.fetchers.base.time.sleep", lambda *_: None)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://api.openalex.org/works").mock(
            return_value=httpx.Response(200, json=OPENALEX_JSON)
        )
        fetcher = OpenAlexFetcher(CONFIG, client=_client())
        papers = fetcher.fetch_by_date_range(START, END)
    assert len(papers) == 1
    p = papers[0]
    assert p.venue == "TPAMI"
    assert p.doi == "10.1109/TPAMI.2026.111"
    assert p.abstract == "We propose a novel method"
    assert p.affiliations == ["Google DeepMind"]
    assert p.code_url == "https://github.com/foo/bar"
    assert "Kaiming He" in p.authors


def test_openreview_parse_and_graceful_degradation(monkeypatch):
    monkeypatch.setattr("paperflow.fetchers.base.time.sleep", lambda *_: None)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://api2.openreview.net/notes").mock(
            return_value=httpx.Response(200, json=OPENREVIEW_JSON)
        )
        fetcher = OpenReviewFetcher(CONFIG, client=_client())
        papers = fetcher.fetch_by_date_range(START, END)
    # ICLR + NeurIPS 都会命中同一 mock；每个 venue 的 rejected 均被过滤，各留 1 篇
    assert len(papers) == 2
    assert all(p.comment for p in papers)
    assert any("Spotlight" in p.comment for p in papers)

    # 404 优雅降级
    with respx.mock(assert_all_called=False) as router:
        router.get("https://api2.openreview.net/notes").mock(
            return_value=httpx.Response(404)
        )
        fetcher = OpenReviewFetcher(CONFIG, client=_client())
        papers = fetcher.fetch_by_date_range(START, END)
    assert papers == []


def test_retry_on_429(monkeypatch):
    """tenacity 对 429 重试，第 3 次成功。"""
    monkeypatch.setattr("paperflow.fetchers.base.time.sleep", lambda *_: None)
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429)
        return httpx.Response(200, text=ARXIV_XML)

    with respx.mock(assert_all_called=False) as router:
        router.get("https://export.arxiv.org/api/query").mock(side_effect=handler)
        fetcher = ArxivFetcher(CONFIG, client=_client())
        papers = fetcher.fetch_by_date_range(START, END)
    assert attempts["n"] == 3
    assert len(papers) == 1


def test_single_adder_extractors():
    assert SinglePaperAdder.extract_arxiv_id("https://arxiv.org/abs/2603.12345") == "2603.12345"
    assert SinglePaperAdder.extract_arxiv_id("https://arxiv.org/pdf/2603.12345.pdf") == "2603.12345"
    assert SinglePaperAdder.extract_doi("https://doi.org/10.1109/TPAMI.2026.111") == "10.1109/TPAMI.2026.111"
    assert SinglePaperAdder.extract_doi("10.1109/TPAMI.2026.111") == "10.1109/TPAMI.2026.111"


def test_rate_limiter(monkeypatch):
    sleeps = []
    vals = iter([0.0, 1.0, 2.0])
    monkeypatch.setattr("paperflow.fetchers.base.time.monotonic", lambda: next(vals))
    monkeypatch.setattr("paperflow.fetchers.base.time.sleep", lambda x: sleeps.append(x))
    limiter = RateLimiter(5.0)
    limiter.wait()  # 首次不等待，last=0.0
    limiter.wait()  # 当前 1.0，距上次 1s < 5s -> 等待 4s
    assert sleeps == [4.0]

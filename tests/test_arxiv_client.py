from lit_orchestrator.subagents.ingest.arxiv_client import _build_search_query, _parse_feed

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2609.19453v2</id>
    <published>2026-09-16T17:01:02Z</published>
    <title>A  Title
      Across Lines</title>
    <summary>  An abstract. </summary>
    <author><name>Ada One</name></author>
    <author><name>Bo Two</name></author>
    <arxiv:comment>12 pages, 4 figures</arxiv:comment>
    <arxiv:primary_category term="cs.LG"/>
    <category term="cs.LG"/>
    <category term="q-bio.QM"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2609.00001v1</id>
    <published>2026-09-15T00:00:00Z</published>
    <title>No comment field</title>
    <summary>x</summary>
    <author><name>Solo</name></author>
    <category term="q-bio.BM"/>
  </entry>
</feed>"""


def test_parse_entry_fields():
    first, second = _parse_feed(FEED)
    assert first["arxiv_id"] == "2609.19453"          # version suffix stripped
    assert first["title"] == "A Title Across Lines"
    assert first["authors"] == ["Ada One", "Bo Two"]
    assert first["categories"] == ["cs.LG", "q-bio.QM"]
    assert first["pages"] == 12
    assert first["published"] == "2026-09-16"
    assert first["source_url"] == "https://arxiv.org/abs/2609.19453"
    assert second["pages"] is None


def test_query_requires_a_category_from_each_list():
    query = _build_search_query(["q-bio.BM", "q-bio.QM"], ["cs.LG", "cs.AI"], lookback_days=5)
    assert query.startswith("(cat:q-bio.BM OR cat:q-bio.QM) AND (cat:cs.LG OR cat:cs.AI) AND submittedDate:[")

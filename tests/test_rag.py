from voxa.rag import KnowledgeBase, chunk_markdown


def test_chunking_keeps_doc_title():
    chunks = chunk_markdown("x.md", "# Doc\n\n## Alpha\nfoo\n\n## Beta\nbar")
    assert [c.title for c in chunks] == ["Doc > Alpha", "Doc > Beta"]


def test_retrieves_the_right_runbook():
    kb = KnowledgeBase.from_dir()
    cases = {
        "connection pool exhausted timeout after deploy": "connection-pool.md",
        "OOMKilled heap memory climbing": "memory-leak.md",
        "failed to resolve host config reloaded": "config-errors.md",
        "bank-gateway partner 503": "third-party-outage.md",
    }
    for query, expected in cases.items():
        assert kb.search(query, 1)[0]["source"].endswith(expected), query


def test_postmortems_are_indexed_and_tool_works():
    kb = KnowledgeBase.from_dir()
    hits = kb.tool().fn(query="gateway latency symptom checkout pool rollback")
    assert any(h["source"].startswith("postmortems/") for h in hits)
    assert kb.search("xyzzy qwerty") == []

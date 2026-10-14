from voxa.memory import IncidentMemory, IncidentRecord


def _rec(service, category, summary, lesson):
    return IncidentRecord({"service": service, "summary": "alert"}, service, category,
                          summary, "rollback_deploy", "resolved", lesson)


def test_recall_finds_similar_incident(tmp_path):
    mem = IncidentMemory(tmp_path / "m.db")
    mem.remember(_rec("checkout", "bad_deploy", "pool exhausted after deploy",
                      "gateway latency was a symptom"))
    mem.remember(_rec("payments", "memory_leak", "heap ramp then OOMKilled", "restart first"))

    hits = mem.recall("checkout latency connection pool")
    assert hits[0]["root_service"] == "checkout"
    assert "Lesson: gateway latency was a symptom" in mem.context("checkout pool")

    # persisted across connections
    assert len(IncidentMemory(tmp_path / "m.db").all()) == 2


def test_empty_memory():
    assert IncidentMemory().recall("anything") == []

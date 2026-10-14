import pytest

from voxa.observability import Tracer


def test_spans_record_tokens_cost_and_events():
    tracer = Tracer()
    events = []
    tracer.subscribe(events.append)
    with tracer.span("llm", "messages.create", agent="logs") as span:
        span.input_tokens, span.output_tokens = 1_000_000, 100_000
    with tracer.span("tool", "search_logs", agent="logs"):
        pass
    summary = tracer.summary("claude-opus-5-5")
    assert summary["llm_calls"] == 1 and summary["tool_calls"] == 1
    assert summary["cost_usd"] == 6.0  # $4 in + $2 out
    assert [e["type"] for e in events] == ["span_start", "span_end"] * 2


def test_span_records_error():
    tracer = Tracer()
    with pytest.raises(ValueError), tracer.span("tool", "boom"):
        raise ValueError("bad")
    assert tracer.spans[0].error == "ValueError: bad"

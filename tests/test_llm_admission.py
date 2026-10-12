import pytest

from software_quality_agent.llm_admission import (
    ModelAdmissionBlocked,
    ModelAdmissionController,
    compact_authoritative_snapshot,
)


class Store:
    def __init__(self, data=None):
        self.data = data or {"model_calls": []}

    def _save(self):
        return None


@pytest.mark.asyncio
async def test_admission_fails_closed_without_a_local_tokenizer():
    store = Store()
    controller = ModelAdmissionController(
        store=store, base_url=None, api_key="", model="fixture",
        context_window=1024, safety_tokens=16,
    )
    with pytest.raises(ModelAdmissionBlocked):
        await controller.check(payload={"messages": [{"role": "user", "content": "中文"}]}, output_reserve=32,
                               compressed=False, agent="review analysis agent")
    assert store.data["llm_state"]["action"] == "abandon"


@pytest.mark.asyncio
async def test_admission_requests_one_compaction_then_blocks_if_compacted_view_still_over_budget():
    store = Store()
    controller = ModelAdmissionController(
        store=store, base_url="http://model/v1", api_key="local", model="fixture",
        context_window=100, safety_tokens=10,
    )
    calls = []

    async def tokenizer(text):
        calls.append(text)
        return 80 if len(calls) == 1 else 95, 100, "ready"

    controller._tokenize = tokenizer
    first = await controller.check(payload={"messages": "large"}, output_reserve=20,
                                   compressed=False, agent="review analysis agent")
    assert first.action == "compress"
    with pytest.raises(ModelAdmissionBlocked) as exc:
        await controller.check(payload={"messages": "still-large"}, output_reserve=20,
                               compressed=True, agent="review analysis agent")
    assert exc.value.code == "context_budget_admission_blocked"
    assert len(calls) == 2
    assert [item["action"] for item in store.data["llm_admission"]] == ["compress", "abandon"]


@pytest.mark.asyncio
async def test_provider_default_output_is_admitted_without_a_hidden_generation_cap():
    store = Store()
    controller = ModelAdmissionController(
        store=store, base_url="http://model/v1", api_key="local", model="fixture",
        context_window=100, safety_tokens=10,
    )

    async def tokenizer(payload):
        return 80, 100, "ready"

    controller._tokenize = tokenizer
    decision = await controller.check(payload={"messages": "input"}, output_reserve=None,
                                      compressed=False, agent="review analysis agent")
    assert decision.action == "allow"
    assert decision.output_reserve is None
    assert store.data["llm_state"]["output_limit_mode"] == "provider_default"
    assert store.data["llm_state"]["available_output_tokens"] == 10


@pytest.mark.asyncio
async def test_provider_default_output_still_compacts_and_blocks_an_oversized_input():
    store = Store()
    controller = ModelAdmissionController(
        store=store, base_url="http://model/v1", api_key="local", model="fixture",
        context_window=100, safety_tokens=10,
    )

    async def tokenizer(payload):
        return 95, 100, "ready"

    controller._tokenize = tokenizer
    decision = await controller.check(payload={"messages": "large"}, output_reserve=None,
                                      compressed=False, agent="review analysis agent")
    assert decision.action == "compress"
    with pytest.raises(ModelAdmissionBlocked) as exc:
        await controller.check(payload={"messages": "still-large"}, output_reserve=None,
                               compressed=True, agent="review analysis agent")
    assert exc.value.code == "context_budget_admission_blocked"
    assert store.data["llm_state"]["output_limit_mode"] == "provider_default"


@pytest.mark.asyncio
async def test_repeated_model_failures_open_circuit_without_another_preflight():
    store = Store({"model_calls": [
        {"status": "blocked", "error_code": "ModelBehaviorError"},
        {"status": "blocked", "error_code": "ModelBehaviorError"},
    ]})
    controller = ModelAdmissionController(
        store=store, base_url=None, api_key="", model="fixture",
        context_window=1024, safety_tokens=16, failure_limit=2,
    )
    with pytest.raises(ModelAdmissionBlocked) as exc:
        await controller.check(payload={"messages": "safe"}, output_reserve=32,
                               compressed=False, agent="review analysis agent")
    assert exc.value.code == "model_failure_circuit_open"
    assert store.data["llm_state"]["health"] == "failed"


def test_compaction_keeps_ids_and_statuses_but_not_full_text():
    snapshot = {"source_segment": {"text": "x" * 4000},
                "all_checks": [{"check_id": "c1", "status": "supported",
                                "statement": "s" * 1000, "source_quote": "q" * 1000,
                                "note": "n" * 1000}],
                "saved_evidence_associations": [{"evidence_id": "e1", "check_id": "c1",
                                                   "design_node_id": "d1", "relation": "supporting"}]}
    compacted = compact_authoritative_snapshot(snapshot)
    assert compacted["source_segment"]["text"] == "x" * 4000
    assert compacted["all_checks"][0]["check_id"] == "c1"
    assert compacted["all_checks"][0]["status"] == "supported"
    assert "source_quote" not in compacted["all_checks"][0]
    assert compacted["all_checks"][0]["details_omitted"]
    assert compacted["saved_evidence_associations"][0]["evidence_id"] == "e1"

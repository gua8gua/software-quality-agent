"""Persisted SDK boundaries; fixtures are not real model evaluation."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_material_workflow import BackendFixture

from software_quality_agent.review_runtime.checkpoint import CheckpointStore
from software_quality_agent.review_runtime.context import SuggestionContext
from software_quality_agent.review_runtime.contracts import SuggestionDraft, SuggestionValidation
from software_quality_agent.tool_definitions.common import _get, _write
from software_quality_agent.review_runtime.control import _assessment_tool_completion, _suggestion_stage, _suggestion_tool_completion
from software_quality_agent.suggestion_workflow import _build_agents


class WorkflowBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.context = SuggestionContext(client=BackendFixture(),
            store=CheckpointStore(Path(self.directory.name), "r", "s"),
            project_id="p", review_id="r", sentence_id="s", tenant_id="local")

    async def test_suggestion_and_validator_require_exact_current_persisted_records(self):
        wrapper = SimpleNamespace(context=self.context)
        draft = self.context.store.save_draft(SuggestionDraft(
            review_id="r", sentence_id="s", segment_id="sentence", problem_summary="gap", suggestion_text="clarify", rationale="insufficient"))
        response = SimpleNamespace(tool=SimpleNamespace(name="save_suggestion_draft"), output=json.dumps(draft))
        self.assertTrue((await _suggestion_tool_completion(wrapper, [response])).is_final_output)
        response.output = json.dumps({**draft, "sentence_id": "foreign"})
        self.assertFalse((await _suggestion_tool_completion(wrapper, [response])).is_final_output)
        feedback = self.context.store.save_validation(SuggestionValidation(review_id="r", sentence_id="s", valid=False,
                                                                            issues=["missing reason"]))
        response.tool.name = "save_suggestion_validation"
        response.output = json.dumps(feedback)
        self.assertTrue((await _assessment_tool_completion(wrapper, [response])).is_final_output)
        response.output = json.dumps({**feedback, "valid": True})
        self.assertFalse((await _assessment_tool_completion(wrapper, [response])).is_final_output)

    async def test_revision_budget_is_an_enforced_transition_not_only_prompt_text(self):
        workspace = await self.context.client.get("/workspace")
        workspace["sentences"][0]["assessment"] = {"finalized": True, "suggestion_required": True, "proposal_fingerprint": "fp"}
        self.context.client.get = AsyncMock(return_value=workspace)
        self.context.store.transition("review_analysis_verified", "completed")
        wrapper = SimpleNamespace(context=self.context)
        for budget in (1, 4):
            self.context.max_suggestion_revisions = budget
            self.context.store.data["suggestion_drafts"] = [
                {"iteration": i + 1, "assessment_fingerprint": "fp"} for i in range(budget)]
            self.context.store.data["validation_feedback"] = [{"draft_iteration": budget, "valid": False}]
            self.assertEqual(await _suggestion_stage(wrapper), "exhausted")
            self.context.store.data["validation_feedback"][-1]["valid"] = True
            self.assertEqual(await _suggestion_stage(wrapper), "complete")
            self.context.store.data["validation_feedback"] = []
            self.assertEqual(await _suggestion_stage(wrapper), "validate")

    async def test_repeated_canonical_reads_do_not_manufacture_execution_failure(self):
        self.context.store.data["current_model_agent"] = "review analysis agent"
        wrapper = SimpleNamespace(context=self.context)
        for _ in range(5):
            self.assertIn("text", json.loads(await _get(wrapper, "get_canonical_node", "/canonical/design")))
        self.assertIsNone(self.context.store.data.get("terminal_tool_error"))

    async def test_sufficient_evidence_stops_investigation_but_keeps_conclusion_tool(self):
        workspace = await self.context.client.get("/workspace")
        async def get(path, params=None):
            return workspace if path.endswith("/workspace") else {
                "can_stop_for_sufficient_evidence": True, "conclusions_complete": False}
        self.context.client.get = get
        agents = _build_agents("unused", {}, self.context)
        wrapper = SimpleNamespace(context=self.context)
        tools = {tool.name: tool for tool in agents["analysis"].tools}
        for name in ("read_review_passage", "get_mandatory_tlr_nodes", "assess_review_check"):
            self.assertFalse(await tools[name].is_enabled(wrapper, agents["analysis"]))
        self.assertTrue(await tools["complete_review_analysis"].is_enabled(wrapper, agents["analysis"]))

    async def test_idempotent_write_cache_distinguishes_different_passages(self):
        self.context.client.write = AsyncMock(side_effect=[{"passage_id": "a"}, {"passage_id": "b"}])
        wrapper = SimpleNamespace(context=self.context)
        first = await _write(wrapper, "assess_review_check", "POST", "/passages/a/assess", {"check_id": "c1"})
        other = await _write(wrapper, "assess_review_check", "POST", "/passages/b/assess", {"check_id": "c1"})
        again = await _write(wrapper, "assess_review_check", "POST", "/passages/a/assess", {"check_id": "c1"})
        self.assertNotEqual(first, other)
        self.assertEqual(first, again)
        self.assertEqual(self.context.client.write.await_count, 2)

    def test_corrupt_checkpoint_is_preserved_not_replaced_by_a_new_attempt(self):
        original = "{broken JSON"
        self.context.store.path.write_text(original, encoding="utf-8")
        loaded = CheckpointStore(Path(self.directory.name), "r", "s")
        with self.assertRaisesRegex(ValueError, "preserved"):
            loaded.begin_attempt()
        self.assertEqual(loaded.path.read_text(encoding="utf-8"), original)

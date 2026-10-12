"""SDK tool-boundary failure policies; no model, database or server calls."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents import RunConfig
from agents.tool_context import ToolContext

from software_quality_agent.config import Settings
from software_quality_agent.review_runtime.checkpoint import CheckpointStore
from software_quality_agent.review_runtime.context import BackendHTTPError, SuggestionContext
from software_quality_agent.review_runtime.contracts import PassageCheckAssessment, SuggestionOutput, SuggestionRequest
from software_quality_agent.review_runtime.control import _conclusion_enabled
from software_quality_agent.suggestion_agent import run_review_suggestions
from software_quality_agent.tool_definitions.common import _review_phase
from software_quality_agent.tool_definitions.material_sequence import read_next_tlr_material
from software_quality_agent.tool_definitions.review_evidence import assess_review_check, finalize_review_passage
from software_quality_agent.tool_definitions.review_progress import finish_review_incomplete, get_review_investigation


class PassageFailurePolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = {
            "sentences": [{"sentence_id": "s", "checks_finalized": True, "checkset_version": 1}],
            "checks": [{"sentence_id": "s", "check_id": "c"}],
            "passages": [{"sentence_id": "s", "passage_id": "p", "design_node_id": "d",
                          "status": "pending", "checkset_version": 1, "start_offset": 0, "end_offset": 5}],
        }
        self.scope = {"unfinished_passage_ids": ["p"], "mandatory_remaining_node_ids": ["d"]}
        self.writes = []
        self.failures = 0
        self.reject_write = False

        async def get(path, params=None):
            if path.endswith("/workspace"):
                return self.workspace
            if path.endswith("/investigation"):
                return self.scope
            return {"text": "设计原文。"}

        async def write(method, path, payload):
            self.writes.append((path, payload))
            if path.endswith("/error"):
                self.failures += 1
                retry = self.failures == 1
                self.workspace["passages"][0]["status"] = "pending" if retry else "blocked"
                return {"passage_id": "p", "execution_status": "retry_required" if retry else "blocked",
                        "error_code": payload["error_code"], "error_message": payload["error_message"],
                        "retry_allowed": retry, "skipped": not retry}
            if self.reject_write:
                raise BackendHTTPError(422, "invalid assessment")
            return {"passage_status": "completed"}

        self.context = SuggestionContext(
            client=SimpleNamespace(get=get, write=write),
            store=CheckpointStore(Path(temporary.name), "r", "s"),
            project_id="project", review_id="r", sentence_id="s", tenant_id="local")

    async def invoke(self, tool, values, call_id="call"):
        arguments = json.dumps(values, ensure_ascii=False)
        ctx = ToolContext(context=self.context, tool_name=tool.name, tool_arguments=arguments,
                          tool_call_id=call_id, run_config=RunConfig(tracing_disabled=True))
        return json.loads(await tool.on_invoke_tool(ctx, arguments))

    def test_schema_and_phase_preserve_satisfaction_over_unfinished_material(self):
        decision = PassageCheckAssessment.model_validate({"check_id": "c", "relation": "irrelevant",
            "status": "pending", "note": "无关", "quotes": [{"invalid": True}]})
        self.assertEqual(decision.quotes, [])
        phase, _ = _review_phase({"can_stop_for_sufficient_evidence": True,
                                 "unfinished_passage_ids": ["p"]}, {"checks_finalized": True})
        self.assertEqual(phase, "conclude_checks")
        self.assertEqual(Settings(_env_file=None, review_model_retry_limit=5).review_model_retry_limit, 1)

    async def test_unused_quotes_do_not_undergo_canonical_matching(self):
        result = await self.invoke(assess_review_check, {"passage_id": "p", "check_id": "c",
            "relation": "irrelevant", "status": "pending", "note": "无关",
            "exact_quotes": ["不在原文中，不应尝试定位"]})
        self.assertEqual(result["passage_status"], "completed")
        self.assertEqual(self.writes[-1][1]["decisions"][0]["quotes"], [])
        self.assertEqual(self.failures, 0)

    async def test_bad_quote_feedback_allows_one_retry_then_skips(self):
        values = {"passage_id": "p", "check_id": "c", "relation": "supporting",
                  "status": "supported", "note": "待校验", "exact_quotes": ["不在原文"]}
        first = await self.invoke(assess_review_check, values, "first")
        self.assertEqual(first["execution_status"], "retry_required")
        self.assertIn("evidence_quote", first["feedback"])
        second = await self.invoke(assess_review_check, values, "second")
        self.assertEqual(second["execution_status"], "blocked")
        self.assertEqual(self.context.store.data["current_review_phase"], "select_next_sds_passage_or_conclude")
        # No additional write is allowed to a skipped range.
        count = len(self.writes)
        await self.invoke(finalize_review_passage, {"passage_id": "p"})
        self.assertEqual(len(self.writes), count)

    async def test_http_rejection_does_not_overwrite_retry_phase_as_success(self):
        self.reject_write = True
        result = await self.invoke(assess_review_check, {"passage_id": "p", "check_id": "c",
            "relation": "context", "status": "pending", "note": "背景", "exact_quotes": ["设计原文。"]})
        self.assertEqual(result["execution_status"], "retry_required")
        self.assertIn("invalid assessment", result["feedback"])
        self.assertIn("再尝试一次", self.context.store.data["current_review_next_action"])

    async def test_supported_checks_stop_even_with_active_partial_passage(self):
        self.scope["can_stop_for_sufficient_evidence"] = True
        result = await self.invoke(read_next_tlr_material, {})
        self.assertEqual(result["execution_status"], "ready_to_conclude")
        self.assertTrue(await _conclusion_enabled(SimpleNamespace(context=self.context), None))
        self.assertFalse(self.writes)

    async def test_status_query_replay_is_not_infinite_and_keeps_failure_feedback(self):
        for i in range(self.context.passage_max_turns + 1):
            result = await self.invoke(get_review_investigation, {}, str(i))
        self.assertEqual(result["execution_status"], "retry_required")
        self.assertEqual(result["error_code"], "no_business_progress")
        self.assertEqual(self.failures, 1)

    async def test_incomplete_exit_cannot_create_semantic_conclusion(self):
        self.scope = {"unfinished_passage_ids": [], "mandatory_unattempted_node_ids": [],
                      "blocked_passage_ids": ["p"], "execution_errors": [{"error_code": "invalid_quote"}]}
        result = await self.invoke(finish_review_incomplete, {})
        self.assertEqual(result["execution_status"], "blocked")
        self.assertIsNone(result["semantic_status"])
        self.assertTrue(self.context.store.data["terminal_tool_error"])

    async def test_model_failure_gets_one_retry_and_next_independent_sentence_runs(self):
        fake_client = SimpleNamespace(get=AsyncMock(return_value={"status": "prepared",
            "sentences": [{"sentence_id": "s"}, {"sentence_id": "other"}]}), close=AsyncMock())
        results = [SuggestionOutput(execution_status="blocked", review_id="r", sentence_id="s",
                                    error_code="model_failure", error_message="真实失败"),
                   SuggestionOutput(execution_status="blocked", review_id="r", sentence_id="s",
                                    error_code="model_failure", error_message="重试失败"),
                   SuggestionOutput(execution_status="completed", review_id="r", sentence_id="other")]
        run = AsyncMock(side_effect=results)
        with patch("software_quality_agent.suggestion_agent.BackendClient", return_value=fake_client), \
                patch("software_quality_agent.suggestion_agent.run_one_suggestion", run):
            result = await run_review_suggestions(settings=SimpleNamespace(quality_backend_url="unused",
                review_model_retry_limit=1), request=SuggestionRequest(project_id="project", review_id="r"))
        self.assertEqual([c.kwargs["sentence_id"] for c in run.await_args_list], ["s", "s", "other"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["sentence_errors"]), 1)

"""SDK wiring and context contracts only; no model or network calls."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from agents import ModelBehaviorError, RunConfig
from agents.items import ModelResponse
from agents.run import CallModelData, ModelInputData
from agents.tool_context import ToolContext
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall
from pydantic import ValidationError

from software_quality_agent.review_runtime.checkpoint import CheckpointStore
from software_quality_agent.review_runtime.contracts import PassageCheckAssessment, ReviewAnalysisTask, SuggestionOutput
from software_quality_agent.review_runtime.context import SuggestionContext
from software_quality_agent.tool_definitions.review_evidence import assess_review_passage, finalize_review_passage, assess_review_check, record_review_evidence, locate_passage_quotes, read_review_passage
from software_quality_agent.tool_definitions.tlr import get_mandatory_tlr_nodes, get_tlr_candidates, get_trace_links, get_run_detail, get_annotations
from software_quality_agent.tool_definitions.canonical import get_node_neighborhood
from software_quality_agent.tool_definitions.saved_results import get_saved_tool_result, saved_result_index
from software_quality_agent.tool_definitions.suggestions import get_suggestion_workspace
from software_quality_agent.tool_definitions.work_notes import get_work_notes
from software_quality_agent.tool_definitions.review_segments import get_review_segment, get_review_history, get_review_workspace_page
from software_quality_agent.review_runtime.model import ObservedChatCompletionsModel, _model_for, _observe_provider_request, _observe_provider_response
from software_quality_agent.review_runtime.hooks import WorkspaceHooks
from software_quality_agent.review_runtime.control import _assessment_tool_completion, _evidence_input_builder, _fatal_nested_failure, _input_builder, _manager_tool_completion, _restore_overall_checkpoint, _terminal_tool_completion
from software_quality_agent.review_runtime.model_input import _admit_model_input, _bounded_model_input, _compact_model_facing_input, _returned_read_index, _index_large_tool_outputs, _unopened_mandatory_reference
from software_quality_agent.suggestion_workflow import _build_agents


class BackendFixture:
    async def get(self, path, params=None):
        if path.endswith("/workspace"):
            return {
                "sentences": [{"sentence_id": "s", "text": "完整语段：在条件C下实现A并满足B。",
                               "checks_finalized": True, "checkset_version": 2}],
                "checks": [{"sentence_id": "s", "check_id": "c1", "statement": "实现A", "status": "pending"},
                           {"sentence_id": "s", "check_id": "c2", "statement": "满足B", "status": "supported"}],
                "evidence": [],
                "passages": [{"passage_id": "passage", "sentence_id": "s", "design_node_id": "design",
                              "start_offset": 0, "end_offset": 5, "status": "pending", "assessments": []}],
            }
        return {"text": "设计原文。"}


class MaterialWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.context = SuggestionContext(
            client=BackendFixture(), store=CheckpointStore(Path(self.directory.name), "r", "s"),
            project_id="p", review_id="r", sentence_id="s", tenant_id="local")

    async def test_cross_sentence_run_and_source_reads_are_low_priority_not_blocked(self):
        self.context.bound_run_id = "run"
        self.context.bound_source_node_id = "source"
        calls = []
        workspace = await self.context.client.get("/workspace")
        workspace["sentences"].append({"sentence_id": "other", "text": "其他需求语段。",
                                       "checks_finalized": True})
        self.context.store.data["current_review_phase"] = "assess_current_passage"

        async def tracking_get(path, params=None):
            calls.append((path, params))
            return workspace if path.endswith("/workspace") else {"items": []}

        self.context.client.get = tracking_get
        for tool, arguments in (
            (get_review_segment, {"sentence_id": "other"}),
            (get_tlr_candidates, {"run_id": "other-run", "source_node_id": "source"}),
            (get_mandatory_tlr_nodes, {"run_id": "other-run", "source_node_id": "other-source"}),
            (get_trace_links, {"run_id": "run", "node_id": "other-source"}),
            (get_run_detail, {"run_id": "other-run"}),
            (get_annotations, {"run_id": "other-run"}),
        ):
            with self.subTest(tool=tool.name):
                context = ToolContext(context=self.context, tool_name=tool.name,
                                      tool_call_id=f"invalid-{tool.name}",
                                      tool_arguments=json.dumps(arguments),
                                      run_config=RunConfig(tracing_disabled=True))
                result = json.loads(await tool.on_invoke_tool(context, json.dumps(arguments)))
                self.assertTrue(result["investigation_priority"].startswith("low_"))
                self.assertNotIn("error_code", result)
        self.assertEqual(len(calls), 6)
        mandatory_params = next(params for path, params in calls if path.endswith("/mandatory"))
        self.assertNotIn("review_id", mandatory_params)
        self.assertEqual(self.context.store.data["current_review_phase"], "assess_current_passage")

    async def test_read_review_passage_outside_selected_scope_is_read_only(self):
        self.context.bound_target_artifact_ids = ("target-artifact",)
        self.context.bound_target_node_ids = ("allowed-node",)
        calls = []
        original_get = self.context.client.get

        async def tracking_get(path, params=None):
            calls.append((path, params))
            return await original_get(path, params)

        self.context.client.get = tracking_get
        arguments = json.dumps({"node_id": "foreign-node", "start_offset": 0,
                                "text_limit": 100})
        context = ToolContext(context=self.context, tool_name=read_review_passage.name,
                              tool_call_id="scope", tool_arguments=arguments,
                              run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await read_review_passage.on_invoke_tool(context, arguments))
        self.assertEqual(result["execution_status"], "read_only")
        self.assertIsNone(result["passage_id"])
        self.assertEqual(result["text"], "设计原文。")
        self.assertFalse(result["canonical_evidence"])
        self.assertTrue(any("/information/nodes/foreign-node" in path for path, _ in calls))
        self.assertNotIn("active_passage_id", self.context.store.data)

    async def test_cross_review_discovery_and_sentence_read_do_not_change_current_phase(self):
        workspace = await self.context.client.get("/workspace")
        self.context.client = SimpleNamespace(get=AsyncMock(return_value=workspace), write=AsyncMock())
        self.context.store.data["current_review_phase"] = "conclude_checks"
        for tool, args in ((get_review_history, {}),
                           (get_review_workspace_page, {"review_id": "other-review"}),
                           (get_review_segment, {"review_id": "other-review", "sentence_id": "s"})):
            ctx = ToolContext(context=self.context, tool_name=tool.name, tool_call_id=tool.name,
                              tool_arguments=json.dumps(args), run_config=RunConfig(tracing_disabled=True))
            result = json.loads(await tool.on_invoke_tool(ctx, json.dumps(args)))
            if tool is not get_review_history:
                self.assertTrue(result["investigation_priority"].startswith("low_"))
                self.assertIn("other-review/workspace", self.context.client.get.call_args.args[0])
        self.assertEqual(self.context.store.data["current_review_phase"], "conclude_checks")
        self.context.client.write.assert_not_awaited()

    async def test_noncurrent_mandatory_read_after_analysis_completion_remains_available(self):
        self.context.bound_run_id = "run"
        self.context.bound_source_node_id = "source"
        self.context.store.transition("review_analysis_verified", "completed", output={})
        self.context.client = SimpleNamespace(get=AsyncMock(return_value={"items": []}), write=AsyncMock())
        args = json.dumps({"run_id": "other-run", "source_node_id": "other-source"})
        ctx = ToolContext(context=self.context, tool_name=get_mandatory_tlr_nodes.name,
                          tool_call_id="foreign-mandatory", tool_arguments=args,
                          run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await get_mandatory_tlr_nodes.on_invoke_tool(ctx, args))
        self.assertEqual(result["current_stage"], "read_only_context")
        self.assertNotIn("review_id", self.context.client.get.call_args.args[1])
        self.context.client.write.assert_not_awaited()

    async def test_unconnected_selected_target_can_be_saved_as_supplementary_passage(self):
        workspace = await self.context.client.get("/workspace")
        self.context.bound_target_artifact_ids = ("target-artifact",)
        self.context.bound_target_node_ids = ("unconnected-node",)
        self.context.client = SimpleNamespace(get=AsyncMock(side_effect=[
            {"node_id": "unconnected-node", "artifact_id": "target-artifact",
             "text": "补充设计证据。", "has_more_text": False}, workspace,
            {"mandatory_remaining_node_ids": []}]),
            write=AsyncMock(return_value={"passage_id": "supplementary-passage"}))
        args = json.dumps({"node_id": "unconnected-node", "candidate_id": None})
        ctx = ToolContext(context=self.context, tool_name=read_review_passage.name,
                          tool_call_id="unconnected", tool_arguments=args,
                          run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await read_review_passage.on_invoke_tool(ctx, args))
        self.assertEqual(result["passage_id"], "supplementary-passage")
        self.assertEqual(result["investigation_priority"], "low_unconnected_tlr")
        payload = self.context.client.write.call_args.args[2]
        self.assertEqual(payload["sentence_id"], "s")
        self.assertEqual(payload["node_id"], "unconnected-node")
        self.assertIsNone(payload["candidate_id"])
        self.assertEqual(payload["end_offset"], len("补充设计证据。"))

    async def test_supplementary_registration_keeps_current_mandatory_priority(self):
        workspace = await self.context.client.get("/workspace")
        self.context.client = SimpleNamespace(get=AsyncMock(side_effect=[
            {"node_id": "unconnected-node", "text": "补充设计证据。"}, workspace,
            {"mandatory_remaining_node_ids": ["mandatory-node"]}]), write=AsyncMock())
        args = json.dumps({"node_id": "unconnected-node", "candidate_id": None})
        ctx = ToolContext(context=self.context, tool_name=read_review_passage.name,
                          tool_call_id="supplement-priority", tool_arguments=args,
                          run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await read_review_passage.on_invoke_tool(ctx, args))
        self.assertEqual(result["error_code"], "supplementary_before_mandatory_complete")
        self.context.client.write.assert_not_awaited()

    def test_compaction_keeps_off_path_read_priority_and_never_makes_it_mandatory(self):
        self.context.bound_run_id = "run"
        self.context.bound_source_node_id = "source"
        record = {"tool": "get_mandatory_tlr_nodes", "arguments": {"run_id": "other-run"},
                  "output": {"run_id": "other-run", "source_node_id": "other-source",
                             "items": [{"node_id": "node", "candidate_id": "foreign-candidate"}],
                             "investigation_priority": "low_unconnected_tlr",
                             "read_scope": "unconnected_tlr_read_only",
                             "read_run_id": "other-run",
                             "candidate_binding_policy": "do_not_bind_foreign_candidate_to_current_review"}}
        self.context.store.data["sdk_tool_results"] = {"foreign-read": record}
        self.assertIsNone(_unopened_mandatory_reference(self.context, {}))
        index = _returned_read_index({"foreign-read": record})[0]
        self.assertEqual(index["read_policy"]["investigation_priority"], "low_unconnected_tlr")
        self.assertEqual(index["result_reference"]["call_id"], "foreign-read")

    async def test_evidence_tools_reject_foreign_check_or_node_before_canonical_read(self):
        self.context.bound_target_node_ids = ("allowed-node",)
        calls = []
        original_get = self.context.client.get

        async def tracking_get(path, params=None):
            calls.append((path, params))
            return await original_get(path, params)

        self.context.client.get = tracking_get
        check_args = json.dumps({"passage_id": "passage", "check_id": "foreign-check",
                                 "relation": "context", "status": "pending", "note": "not this sentence"})
        check_context = ToolContext(context=self.context, tool_name=assess_review_check.name,
                                    tool_call_id="foreign-check", tool_arguments=check_args,
                                    run_config=RunConfig(tracing_disabled=True))
        check_result = await assess_review_check.on_invoke_tool(check_context, check_args)
        self.assertIn("check is outside current Agent sentence", check_result)

        evidence_args = json.dumps({"check_id": "foreign-check", "node_id": "foreign-node",
                                    "exact_quote": "quote"})
        evidence_context = ToolContext(context=self.context, tool_name=record_review_evidence.name,
                                      tool_call_id="foreign-evidence", tool_arguments=evidence_args,
                                      run_config=RunConfig(tracing_disabled=True))
        evidence_result = await record_review_evidence.on_invoke_tool(evidence_context, evidence_args)
        self.assertIn("check is outside current Agent sentence", evidence_result)
        self.assertFalse(any("/information/nodes/foreign-node" in path for path, _ in calls))

    async def test_neighborhood_tool_preserves_explicit_page_offsets(self):
        self.context.client = SimpleNamespace(get=AsyncMock(return_value={"children": []}))
        arguments = json.dumps({"node_id": "canonical", "child_offset": 20,
                                "child_limit": 5, "sibling_offset": 4, "sibling_limit": 2})
        context = ToolContext(context=self.context, tool_name="get_node_neighborhood",
                              tool_call_id="neighbors", tool_arguments=arguments,
                              run_config=RunConfig(tracing_disabled=True))
        await get_node_neighborhood.on_invoke_tool(context, arguments)
        params = self.context.client.get.call_args.args[1]
        self.assertEqual(params["child_offset"], 20)
        self.assertEqual(params["sibling_offset"], 4)
        indexed = _returned_read_index({"neighbors": {
            "tool": "get_node_neighborhood", "arguments": arguments,
            "output": {"children": [], "children_total": 20, "children_has_more": False,
                       "children_next_offset": None}}})
        self.assertFalse(indexed[0]["pagination"]["children_has_more"])
        self.assertIsNone(indexed[0]["pagination"]["children_next_offset"])

    def test_sdk_tools_are_material_driven_not_point_driven(self):
        agents = _build_agents("unused-model", {"review_id": "r", "sentence_id": "s"}, self.context)
        names = {tool.name for tool in agents["analysis"].tools}
        self.assertIn("investigate_review_material", names)
        self.assertIn("assess_review_check", names)
        self.assertIn("finalize_review_passage", names)
        self.assertNotIn("assess_review_passage", names)
        self.assertNotIn("investigate_verification_point", names)
        self.assertNotIn("mark_mandatory_node_visited", names)
        self.assertNotIn("update_review_check", names)
        for role in ("analysis", "evidence"):
            tool_names = {tool.name for tool in agents[role].tools}
            self.assertTrue({"get_run_history", "get_run_detail", "get_tlr_candidates", "get_trace_links",
                             "get_review_history", "get_review_workspace_page", "get_review_segment"}
                            <= tool_names)
            self.assertIn("低优先级上下文", agents[role].instructions)
        self.assertIn("can_stop_for_sufficient_evidence", agents["analysis"].instructions)
        self.assertEqual(agents["analysis"].model_settings.tool_choice, "required")
        self.assertEqual(agents["manager"].model_settings.tool_choice, "required")
        self.assertIsNone(agents["web"].model_settings.tool_choice)
        from agents.run_internal.tool_execution import maybe_reset_tool_choice
        tracker = SimpleNamespace(has_used_tools=lambda agent: True)
        for role in ("analysis", "manager", "suggestion", "validator", "evidence"):
            agent = agents[role]
            self.assertFalse(agent.reset_tool_choice)
            self.assertEqual(maybe_reset_tool_choice(agent, tracker, agent.model_settings).tool_choice, "required")
            self.assertTrue(callable(agent.tool_use_behavior))
        schema = next(t.params_json_schema for t in agents["analysis"].tools
                      if t.name == "investigate_review_material")
        self.assertNotIn("check_id", schema["properties"])

    def test_review_and_evidence_agents_do_not_set_a_generation_token_limit(self):
        agents = _build_agents("unused-model", {}, self.context)
        self.assertIsNone(agents["analysis"].model_settings.max_tokens)
        self.assertIsNone(agents["evidence"].model_settings.max_tokens)
        # This request removes the two fixed 512 caps, not unrelated role budgets.
        self.assertEqual(agents["manager"].model_settings.max_tokens, 1536)

    async def test_pre_model_admission_accepts_provider_default_output_policy(self):
        model = ObservedChatCompletionsModel(store=self.context.store, model="unused", openai_client=None)
        agent = _build_agents(model, {}, self.context)["analysis"]
        bounded = ModelInputData(input=[{"role": "user", "content": "task"}], instructions="role")
        with patch("software_quality_agent.review_runtime.model_input.ModelAdmissionController.check",
                   new=AsyncMock(return_value=SimpleNamespace(action="allow"))) as check:
            result = await _admit_model_input(CallModelData(
                model_data=bounded, agent=agent, context=self.context), bounded)
        self.assertIs(result, bounded)
        self.assertIsNone(check.await_args.kwargs["output_reserve"])

    async def test_request_admission_does_not_reintroduce_an_omitted_output_limit(self):
        model, client = _model_for(SimpleNamespace(suggestion_base_url="http://local-model/v1",
            suggestion_api_key="fixture-only", suggestion_model="unused"), self.context.store)
        self.context.store.data["model_calls"] = [{"status": "running"}]
        request = httpx.Request("POST", "http://local-model/v1/chat/completions",
                                json={"model": "unused", "messages": [{"role": "user", "content": "task"}]})
        try:
            with patch("software_quality_agent.review_runtime.model_input.ModelAdmissionController.check",
                       new=AsyncMock(return_value=SimpleNamespace(action="allow"))) as check:
                await client._client.event_hooks["request"][0](request)
            self.assertIsNone(check.await_args.kwargs["output_reserve"])
            self.assertNotIn("max_tokens", json.loads(request.content))
            self.assertNotIn("max_tokens", self.context.store.data["model_calls"][-1]["provider_request"])
        finally:
            await client.close()

    async def test_specialist_returns_to_manager_only_after_current_successful_write(self):
        wrapper = SimpleNamespace(context=self.context)
        proposal = {"sentence_id": "s", "proposal_fingerprint": "fp", "proposal": {"status": "issues"}}
        result = SimpleNamespace(tool=SimpleNamespace(name="propose_review_assessment"), output=json.dumps(proposal))
        self.assertFalse((await _assessment_tool_completion(wrapper, [result])).is_final_output)
        self.context.store.transition("review_analysis_verified", "completed")
        self.context.store.transition("overall_assessment_proposed", "completed", output=proposal)
        self.assertTrue((await _assessment_tool_completion(wrapper, [result])).is_final_output)
        result.output = "Tool failed; please try again"
        self.assertFalse((await _assessment_tool_completion(wrapper, [result])).is_final_output)
        result.output = json.dumps({**proposal, "proposal_fingerprint": "not-saved"})
        self.assertFalse((await _assessment_tool_completion(wrapper, [result])).is_final_output)
        result.output = json.dumps(proposal)
        result.tool.name = "get_review_segment"
        self.assertFalse((await _assessment_tool_completion(wrapper, [result])).is_final_output)
        agents = _build_agents("unused", {}, self.context)
        self.assertIs(agents["analysis"].tool_use_behavior, _assessment_tool_completion)
        self.assertIs(agents["validator"].tool_use_behavior, _assessment_tool_completion)
        self.assertTrue(agents["analysis"].output_guardrails)
        self.assertTrue(agents["validator"].output_guardrails)

    async def test_rejection_returns_feedback_without_accepting_proposal(self):
        value = {"sentence_id": "s", "validation": {"accepted": False, "reason": "missing source requirement"}}
        self.context.store.transition("overall_assessment_validation", "completed", output=value)
        self.context.store.transition("overall_assessment_proposed", "revision_required", output=value)
        result = SimpleNamespace(tool=SimpleNamespace(name="validate_review_assessment"), output=json.dumps(value))
        self.assertTrue((await _assessment_tool_completion(SimpleNamespace(context=self.context), [result])).is_final_output)
        self.assertFalse(self.context.store.stage_complete("overall_assessment_validated"))

    async def test_pending_current_proposal_resumes_validator_without_regenerating_analysis(self):
        self.context.store.transition("review_analysis_verified", "completed", output={"completed": True})
        assessment = {"finalized": False, "proposal_current": True, "pending_reason": "awaiting_overall_validation",
                      "proposal_fingerprint": "saved-fingerprint",
                      "proposal": {"status": "issues", "evaluation_text": "已保存完整评价", "issues": []},
                      "validation": {}}
        _restore_overall_checkpoint(self.context, {"assessment": assessment})
        agents = _build_agents("unused-model", {}, self.context)
        tools = {tool.name: tool for tool in agents["manager"].tools}
        wrapper = SimpleNamespace(context=self.context)
        self.assertFalse(tools["run_review_analysis"].is_enabled(wrapper, agents["manager"]))
        self.assertTrue(await tools["validate_segment_assessment"].is_enabled(wrapper, agents["manager"]))
        self.assertFalse(self.context.store.stage_complete("overall_assessment_validated"))
        self.assertEqual(self.context.store.data["stage_outputs"]["overall_assessment_proposed"], assessment)

    def test_rejected_changed_or_incomplete_proposals_do_not_restore_validation_stage(self):
        self.context.store.transition("review_analysis_verified", "completed", output={"completed": True})
        base = {"finalized": False, "proposal_current": True, "pending_reason": "awaiting_overall_validation",
                "proposal_fingerprint": "saved", "proposal": {"status": "implemented"}, "validation": {}}
        for updates in ({"pending_reason": "overall_assessment_rejected", "validation": {"accepted": False}},
                        {"pending_reason": "assessment_facts_changed", "proposal_current": False},
                        {"validation": {"accepted": False, "reason": "审核拒绝"}},
                        {"proposal_current": False},
                        {"proposal_fingerprint": ""}, {"proposal": {}}):
            _restore_overall_checkpoint(self.context, {"assessment": {**base, **updates}})
            self.assertFalse(self.context.store.stage_complete("overall_assessment_proposed"))

    async def test_current_proposal_resumes_validation_despite_saved_execution_failure(self):
        self.context.store.transition("review_analysis_verified", "completed", output={"completed": True})
        assessment = {"finalized": False, "proposal_current": True,
                      "status": "analysis_error", "pending_reason": "execution_failed",
                      "proposal": {"status": "implemented", "evaluation_text": "真实已保存提案", "issues": []},
                      "proposal_fingerprint": "unchanged-facts-and-proposal", "validation": {}}
        _restore_overall_checkpoint(self.context, {"assessment": assessment})
        agents = _build_agents("unused-model", {}, self.context)
        tools = {tool.name: tool for tool in agents["manager"].tools}
        wrapper = SimpleNamespace(context=self.context)
        self.assertFalse(tools["run_review_analysis"].is_enabled(wrapper, agents["manager"]))
        self.assertTrue(await tools["validate_segment_assessment"].is_enabled(wrapper, agents["manager"]))
        self.assertFalse(self.context.store.stage_complete("overall_assessment_validated"))
        self.assertEqual(self.context.store.data["stage_outputs"]["overall_assessment_proposed"]["status"], "analysis_error")

    def test_pending_proposal_does_not_fabricate_an_analysis_completion_checkpoint(self):
        _restore_overall_checkpoint(self.context, {"assessment": {
            "pending_reason": "awaiting_overall_validation", "proposal_current": True, "proposal": {"status": "issues"},
            "proposal_fingerprint": "saved", "validation": {}}})
        self.assertFalse(self.context.store.stage_complete("review_analysis_verified"))
        self.assertFalse(self.context.store.stage_complete("overall_assessment_proposed"))

    async def test_every_model_call_rehydrates_source_all_checks_and_exact_active_passage(self):
        agents = _build_agents("unused-model", {}, self.context)
        self.context.store.data["active_passage_id"] = "passage"
        history = [{"role": "user", "content": f"old message {i}"} for i in range(9)]
        data = CallModelData(model_data=ModelInputData(input=history, instructions="role"),
                             agent=agents["analysis"], context=self.context)
        result = await _bounded_model_input(data)
        snapshot = json.loads(result.input[1]["content"].split(": ", 1)[1])
        self.assertEqual(snapshot["source_segment"]["text"], "完整语段：在条件C下实现A并满足B。")
        self.assertEqual({c["check_id"] for c in snapshot["all_checks"]}, {"c1", "c2"})
        self.assertEqual(snapshot["active_passage"]["exact_text"], "设计原文。")
        self.assertEqual(result.input[0], history[0])
        self.assertEqual(result.input[2:], history[1:])

    async def test_context_keeps_complete_tool_history_before_budget_pressure(self):
        agents = _build_agents("unused", {}, self.context)
        history = [{"role": "user", "content": "task"}]
        for number in range(6):
            history.extend([
                {"type": "function_call", "call_id": str(number), "name": "get_node_path", "arguments": "{}"},
                {"type": "function_call_output", "call_id": str(number), "output": "{}"},
            ])
        result = await _bounded_model_input(CallModelData(
            model_data=ModelInputData(input=history, instructions="role"),
            agent=agents["manager"], context=self.context))
        self.assertEqual(result.input, history)

    async def test_large_docling_metadata_is_addressable_after_admission_compression(self):
        agents = _build_agents("unused", {}, self.context)
        original = {"node_id": "root", "text": "Exact original text", "text_start": 0,
                    "has_more_text": False, "hierarchy": {
                        "docling_children_refs": [f"#/texts/{i}" for i in range(3000)]}}
        self.context.store.data["sdk_tool_results"] = {
            "root-read": {"tool": "get_canonical_node", "output": original}}
        history = [{"role": "user", "content": "task"},
                   {"type": "function_call", "call_id": "root-read", "name": "get_canonical_node", "arguments": "{}"},
                   {"type": "function_call_output", "call_id": "root-read", "output": json.dumps(original)}]
        indexed = _index_large_tool_outputs(history, self.context.store.data["sdk_tool_results"])
        view = json.loads(indexed[-1]["output"])
        self.assertEqual(view["text"], original["text"])
        self.assertEqual(view["hierarchy"]["fields"]["docling_children_refs"]["read"]["field_path"],
                         ["hierarchy", "docling_children_refs"])
        self.assertLess(len(indexed[-1]["output"]), 1000)
        self.assertEqual(len(original["hierarchy"]["docling_children_refs"]), 3000)

    def test_compaction_retains_read_addresses_without_claiming_semantic_success(self):
        records = {
            "old": {"tool": "get_node_path", "arguments": '{"node_id":"source"}', "output": {}},
            "latest": {"tool": "get_node_path", "arguments": '{"node_id":"source"}', "output": {}},
            "page": {"tool": "get_saved_tool_result", "arguments": '{"call_id":"latest","field_path":["path"]}',
                     "output": {"has_more": False, "next_offset": None}},
        }
        ledger = _returned_read_index(records)
        self.assertEqual(len(ledger), 2)
        self.assertEqual(ledger[0]["result_reference"]["call_id"], "latest")
        self.assertIsNone(ledger[1]["pagination"]["next_offset"])
        history = [{"role": "user", "content": "task"},
                   {"type": "function_call", "call_id": "page", "name": "get_saved_tool_result", "arguments": "{}"},
                   {"type": "function_call_output", "call_id": "page", "output": "{}"}]
        compacted = _compact_model_facing_input(history, records)
        self.assertEqual(compacted[-2:], history[-2:])
        self.assertIn('"call_id":"latest"', compacted[1]["content"])
        self.assertNotIn("supported", compacted[1]["content"])

    async def test_long_rehydrated_source_is_paged_without_silent_truncation(self):
        long_text = "条件与功能。" * 1200
        workspace = await self.context.client.get("/workspace")
        workspace["sentences"][0]["text"] = long_text
        workspace["sentences"][0]["checks_finalized"] = False
        agents = _build_agents("unused-model", {}, self.context)
        with patch("software_quality_agent.review_runtime.model_input._workspace",
                   new=AsyncMock(return_value=workspace)):
            result = await _bounded_model_input(CallModelData(
                model_data=ModelInputData(input=[{"role": "user", "content": "task"}], instructions="role"),
                agent=agents["analysis"], context=self.context))
        snapshot = json.loads(result.input[1]["content"].split(": ", 1)[1])
        source = snapshot["source_segment"]
        self.assertEqual(len(source["text"]), 4000)
        self.assertTrue(source["text_has_more"])
        self.assertEqual(source["text_next_start"], 4000)
        self.assertIn("get_review_segment", source["text_read_instruction"])

    async def test_investigator_gets_all_checks_and_rejects_foreign_scope(self):
        builder = _evidence_input_builder({}, self.context)
        params = {"review_id": "r", "sentence_id": "s", "investigation_goal": "调查剩余设计资料"}
        task = json.loads(await builder({"params": params}))
        self.assertEqual({c["check_id"] for c in task["all_checks"]}, {"c1", "c2"})
        with self.assertRaises(ValueError):
            await builder({"params": {**params, "sentence_id": "other"}})

    async def test_specialist_identity_is_host_bound_not_model_generated(self):
        agents = _build_agents("unused-model", {}, self.context)
        for role in ("manager", "analysis"):
            for tool in agents[role].tools:
                if tool.name in {"run_review_analysis", "validate_segment_assessment",
                                 "draft_modification_suggestion", "validate_modification_suggestion",
                                 "investigate_review_material", "research_external_context", "research_web_context"}:
                    self.assertNotIn("review_id", tool.params_json_schema["properties"])
                    self.assertNotIn("sentence_id", tool.params_json_schema["properties"])
                    self.assertFalse(tool.params_json_schema["additionalProperties"])
        task = json.loads(_input_builder({}, context=self.context)({"params": {}}))
        self.assertEqual((task["review_id"], task["sentence_id"]), ("r", "s"))
        evidence_task = json.loads(await _evidence_input_builder({}, self.context)(
            {"params": {"investigation_goal": "寻找必要的约束证据"}}))
        self.assertEqual(evidence_task["sentence_id"], "s")
        self.assertEqual(len(evidence_task["all_checks"]), 2)
        with self.assertRaises(ValidationError):
            ReviewAnalysisTask.model_validate({"sentence_id": "typo"})
        with self.assertRaises(ValueError):
            _input_builder({}, context=self.context)({"params": {"sentence_id": "foreign"}})

    async def test_mandatory_candidate_pages_are_transport_bounded(self):
        self.context.bound_run_id = "run"
        self.context.bound_source_node_id = "source"
        context = ToolContext(context=self.context, tool_name="get_mandatory_tlr_nodes",
                              tool_call_id="mandatory", tool_arguments=json.dumps({"limit": 100}),
                              run_config=RunConfig(tracing_disabled=True))
        with patch("software_quality_agent.tool_definitions.review_evidence._get",
                   new=AsyncMock(return_value=json.dumps({"items": [], "has_more": False})) ) as request:
            await get_mandatory_tlr_nodes.on_invoke_tool(context, json.dumps({"limit": 100}))
        self.assertEqual(request.await_args.args[3]["limit"], 3)

    async def test_mandatory_page_honors_explicit_offset_on_reread(self):
        self.context.bound_run_id = "run"
        self.context.bound_source_node_id = "source"
        page0 = {"items": [{"node_id": "n0"}], "has_more": True, "next_offset": 3}
        page3 = {"items": [{"node_id": "n3"}], "has_more": False, "next_offset": None}
        client = SimpleNamespace(get=AsyncMock(side_effect=[page0, page0, page3]))
        self.context.client = client
        tool_context = ToolContext(context=self.context, tool_name="get_mandatory_tlr_nodes",
                                   tool_call_id="mandatory", tool_arguments="{}",
                                   run_config=RunConfig(tracing_disabled=True))
        first = json.loads(await get_mandatory_tlr_nodes.on_invoke_tool(
            tool_context, json.dumps({"offset": 0, "limit": 100})))
        second = json.loads(await get_mandatory_tlr_nodes.on_invoke_tool(
            tool_context, json.dumps({"offset": 0, "limit": 100})))
        self.assertEqual(first["items"][0]["node_id"], "n0")
        self.assertEqual(second["items"][0]["node_id"], "n0")
        self.assertNotIn("cursor_adjustment", second)
        self.assertEqual(client.get.await_args_list[1].args[1]["offset"], 0)

    def test_exact_quote_offsets_are_deterministic_and_range_bound(self):
        decision = PassageCheckAssessment(check_id="c", relation="supporting", status="supported",
                                           note="逐字证据", quotes=[{"exact_quote": "HTML 5.0 标准"}])
        row = locate_passage_quotes([decision], "代码遵照HTML 5.0 标准。", 90)[0]
        self.assertEqual(row["quotes"][0]["start_offset"], 94)
        self.assertEqual(row["quotes"][0]["end_offset"], 105)
        for invalid in ["别的设计文本", "HTML 5.0 标准与HTML 5.0 标准"]:
            with self.assertRaises(ValueError):
                locate_passage_quotes([decision], invalid, 0)

    def test_failure_closes_public_agent_states_without_fabricating_results(self):
        self.context.store.transition("review_analysis", "running")
        self.context.store.output(SuggestionOutput(execution_status="blocked", review_id="r",
                                                 sentence_id="s", error_code="timeout", error_message="test"))
        state = self.context.store.data["agent_states"]["review_analysis"]
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["error_code"], "timeout")
        self.assertEqual(self.context.store.data["latest_output"]["suggestion_text"], "")

    async def test_nested_failure_overrides_an_end_hook_that_ran_before_guardrail(self):
        for tool_name, hook_stage, expected_stage in (
            ("run_review_analysis", "review_analysis", "review_analysis"),
            ("investigate_review_material", "evidence", "evidence"),
            ("validate_segment_assessment", "validator", "assessment_validator"),
            ("draft_modification_suggestion", "suggestion", "suggestion"),
            ("validate_modification_suggestion", "validator", "suggestion_validator"),
        ):
            with self.subTest(tool=tool_name):
                wrapper = SimpleNamespace(context=self.context, tool_name=tool_name)
                await WorkspaceHooks(hook_stage).on_end(wrapper, None, "unpersisted model prose")
                self.assertTrue(self.context.store.stage_complete(expected_stage))
                with self.assertRaisesRegex(RuntimeError, "specialist_execution_failed"):
                    _fatal_nested_failure(wrapper, RuntimeError("guardrail rejected incomplete workspace"))
                self.assertFalse(self.context.store.stage_complete(expected_stage))
                self.assertEqual(self.context.store.data["agent_states"][expected_stage]["status"], "blocked")
                self.assertEqual(self.context.store.data["stage_outputs"][expected_stage], "unpersisted model prose")
        self.assertNotIn("evidence_investigator", self.context.store.data["agent_states"])

    async def test_empty_sdk_response_is_an_execution_error_not_another_model_turn(self):
        model = ObservedChatCompletionsModel(store=self.context.store, model="unused", openai_client=None)
        empty = ModelResponse(output=[], usage=Usage(requests=1, output_tokens=512), response_id="fixture")
        with patch("agents.models.openai_chatcompletions.OpenAIChatCompletionsModel.get_response",
                   new=AsyncMock(return_value=empty)), self.assertRaises(ModelBehaviorError):
            await model.get_response()
        self.assertEqual(len(self.context.store.data["model_calls"]), 1)
        self.assertEqual(self.context.store.data["model_calls"][0]["status"], "blocked")

    async def test_large_tool_result_is_saved_intact_with_explicit_retrieval_id(self):
        original = json.dumps({"items": [{"node_id": "real-id", "text": "逐字原文" * 500}]}, ensure_ascii=False)
        hook = WorkspaceHooks("suggestion")
        await hook.on_tool_end(SimpleNamespace(context=self.context, tool_call_id="real-call"), None,
                               SimpleNamespace(name="get_artifact_outline"), original)
        agents = _build_agents("unused", {}, self.context)
        history = [{"role": "user", "content": "task"},
                   {"type": "function_call", "call_id": "real-call", "name": "get_artifact_outline", "arguments": "{}"},
                   {"type": "function_call_output", "call_id": "real-call", "output": original}]
        result = await _bounded_model_input(CallModelData(
            model_data=ModelInputData(input=history, instructions="role"), agent=agents["suggestion"], context=self.context))
        descriptor = json.loads(result.input[-1]["output"])
        self.assertEqual(descriptor["call_id"], "real-call")
        self.assertEqual(descriptor["fields"]["items"]["length"], 1)
        self.assertEqual(self.context.store.data["sdk_tool_results"]["real-call"]["output"]["items"][0]["text"], "逐字原文" * 500)
        self.assertIn("get_saved_tool_result", {t.name for t in agents["suggestion"].tools})

    async def test_manager_terminal_handler_requires_independently_validated_whole_assessment(self):
        ctx = SimpleNamespace(context=self.context)
        tool_result = SimpleNamespace(tool=SimpleNamespace(name="run_review_analysis"))
        self.assertFalse((await _manager_tool_completion(ctx, [tool_result])).is_final_output)
        self.context.store.transition("review_analysis_verified", "completed")
        workspace = await self.context.client.get("/workspace")
        for check in workspace["checks"]:
            check["status"] = "supported"
        workspace["sentences"][0]["assessment"] = {"finalized": True, "suggestion_required": False}
        with patch("software_quality_agent.review_runtime.control._workspace", new=AsyncMock(return_value=workspace)), patch(
                "software_quality_agent.review_runtime.control._project_persisted_result", new=AsyncMock(return_value=
                    SuggestionOutput(execution_status="completed", review_id="r", sentence_id="s"))):
            self.assertFalse((await _manager_tool_completion(ctx, [tool_result])).is_final_output)
            self.context.store.transition("overall_assessment_validated", "completed")
            self.assertTrue((await _manager_tool_completion(ctx, [tool_result])).is_final_output)
            workspace["sentences"][0]["assessment"]["suggestion_required"] = True
            self.assertFalse((await _manager_tool_completion(ctx, [tool_result])).is_final_output)

    async def test_saved_list_paging_advances_and_never_recursively_wraps_the_same_value(self):
        rows = [{"node_id": str(i), "text": "原文" * 80} for i in range(12)]
        self.context.store.data["sdk_tool_results"] = {"original": {"tool": "search", "output": {"items": rows}}}
        offset = 0
        recovered = []
        while offset is not None:
            arguments = json.dumps({"call_id": "original", "field_path": ["items"], "offset": offset, "limit": 100})
            context = ToolContext(context=self.context, tool_name="get_saved_tool_result",
                                  tool_call_id=f"page-{offset}", tool_arguments=arguments,
                                  run_config=RunConfig(tracing_disabled=True))
            page = json.loads(await get_saved_tool_result.on_invoke_tool(context, arguments))
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False)), 1000)
            if page["has_more"]:
                self.assertGreater(page["next_offset"], offset)
            else:
                self.assertIsNone(page["next_offset"])
            recovered.extend(page["value"])
            offset = page["next_offset"]
        self.assertEqual(recovered, rows)

    async def test_saved_small_objects_return_values_not_another_field_index(self):
        original = {"pending": 2, "supported": 0, "checks_finalized": False}
        self.context.store.data["sdk_tool_results"] = {"original": {"tool": "progress", "output": original}}
        arguments = json.dumps({"call_id": "original", "field_path": [], "offset": 0, "limit": 100})
        context = ToolContext(context=self.context, tool_name="get_saved_tool_result",
                              tool_call_id="page", tool_arguments=arguments,
                              run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await get_saved_tool_result.on_invoke_tool(context, arguments))
        self.assertEqual(result["value"], original)
        self.assertNotIn("fields", result)

    async def test_saved_empty_and_last_pages_have_no_continuation(self):
        for value in ([], "", ["one"], "one"):
            with self.subTest(value=value):
                self.context.store.data["sdk_tool_results"] = {
                    "original": {"tool": "read", "output": {"items": value}}}
                arguments = json.dumps({"call_id": "original", "field_path": ["items"],
                                        "offset": 0, "limit": 100})
                context = ToolContext(context=self.context, tool_name="get_saved_tool_result",
                                      tool_call_id="page", tool_arguments=arguments,
                                      run_config=RunConfig(tracing_disabled=True))
                page = json.loads(await get_saved_tool_result.on_invoke_tool(context, arguments))
                self.assertEqual(page["value"], value)
                self.assertFalse(page["has_more"])
                self.assertIsNone(page["next_offset"])

    async def test_saved_invalid_address_is_a_recorded_execution_failure(self):
        for value, path, offset in (([], ["items"], 1), ("", ["items"], 101),
                                    (["one"], ["items"], 1), ({}, ["items"], 2),
                                    ([], ["missing"], 0), ([], ["items", "0"], 0)):
            with self.subTest(value=value, path=path, offset=offset):
                self.context.store.data["sdk_tool_results"] = {
                    "original": {"tool": "read", "output": {"items": value}}}
                arguments = json.dumps({"call_id": "original", "field_path": path,
                                        "offset": offset, "limit": 100})
                context = ToolContext(context=self.context, tool_name="get_saved_tool_result",
                                      tool_call_id="page", tool_arguments=arguments,
                                      run_config=RunConfig(tracing_disabled=True))
                with self.assertRaisesRegex(ModelBehaviorError, "saved_result_address_invalid"):
                    await get_saved_tool_result.on_invoke_tool(context, arguments)
                self.assertEqual(self.context.store.data["terminal_tool_error"]["error_code"],
                                 "saved_result_address_invalid")

    def test_saved_index_inlines_empty_containers(self):
        index = saved_result_index("call", "neighborhood", {"children": [], "metadata": {}})
        self.assertEqual(index["fields"]["children"], {"value": []})
        self.assertEqual(index["fields"]["metadata"], {"value": {}})

    async def test_saved_result_allows_default_root_arguments(self):
        original = {"active_passage": {"passage_id": "p"}, "items": []}
        self.context.store.data["sdk_tool_results"] = {
            "original": {"tool": "progress", "output": original}}
        arguments = json.dumps({"call_id": "original"})
        context = ToolContext(context=self.context, tool_name="get_saved_tool_result",
                              tool_call_id="root", tool_arguments=arguments,
                              run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await get_saved_tool_result.on_invoke_tool(context, arguments))
        self.assertEqual(result["value"], original)

    async def test_saved_result_replay_is_idempotent_and_marked_without_blocking(self):
        self.context.store.data["sdk_tool_results"] = {
            "original": {"tool": "search", "output": {"items": [{"node_id": "a"}]}}
        }
        args = json.dumps({"call_id": "original", "field_path": ["items"], "offset": 0, "limit": 10})
        context = ToolContext(context=self.context, tool_name="get_saved_tool_result",
                              tool_call_id="page-0", tool_arguments=args,
                              run_config=RunConfig(tracing_disabled=True))
        first = json.loads(await get_saved_tool_result.on_invoke_tool(context, args))
        self.assertIn("value", first)
        second = json.loads(await get_saved_tool_result.on_invoke_tool(context, args))
        self.assertEqual(second["value"], first["value"])
        self.assertTrue(second["already_read"])
        self.assertIsNone(self.context.store.data["terminal_tool_error"])
        self.assertEqual(len(self.context.store.data["saved_page_replays"]), 1)
        third = json.loads(await get_saved_tool_result.on_invoke_tool(context, args))
        self.assertEqual(third["value"], first["value"])
        self.assertIsNone(self.context.store.data["terminal_tool_error"])

    async def test_saved_result_backward_string_page_returns_requested_bytes(self):
        self.context.store.data["sdk_tool_results"] = {
            "original": {"tool": "error", "output": {"error_message": "x" * 240}}}
        context = ToolContext(context=self.context, tool_name="get_saved_tool_result",
                              tool_call_id="page", tool_arguments="{}",
                              run_config=RunConfig(tracing_disabled=True))
        first = json.loads(await get_saved_tool_result.on_invoke_tool(
            context, json.dumps({"call_id": "original", "field_path": ["error_message"],
                                 "offset": 0, "limit": 100})))
        second = json.loads(await get_saved_tool_result.on_invoke_tool(
            context, json.dumps({"call_id": "original", "field_path": ["error_message"],
                                 "offset": 100, "limit": 100})))
        replay = json.loads(await get_saved_tool_result.on_invoke_tool(
            context, json.dumps({"call_id": "original", "field_path": ["error_message"],
                                 "offset": 0, "limit": 100})))
        self.assertEqual(first["offset"], 0)
        self.assertEqual(second["offset"], 100)
        self.assertTrue(replay["already_read"])
        self.assertEqual(replay["offset"], 0)
        self.assertEqual(replay["value"], first["value"])
        self.assertTrue(replay["has_more"])

    def test_saved_index_exposes_values_and_complete_nested_read_arguments(self):
        index = saved_result_index("call", "segment", {"sentence_id": "s", "text": "原文" * 1000}, ["sentence"])
        self.assertEqual(index["fields"]["sentence_id"]["value"], "s")
        self.assertEqual(index["fields"]["text"]["read"]["field_path"], ["sentence", "text"])

    async def test_business_tool_values_remain_visible_after_old_history_is_trimmed(self):
        agents = _build_agents("unused", {}, self.context)
        output = {"review_id": "r", "assessment": {"status": "pending"}, "reason": "事实" * 900}
        self.context.store.data["sdk_tool_results"] = {"last": {"tool": "get_review_progress", "output": output}}
        items = [{"role": "user", "content": "task"},
                 {"type": "function_call", "call_id": "last", "name": "get_review_progress", "arguments": "{}"},
                 {"type": "function_call_output", "call_id": "last", "output": json.dumps(output, ensure_ascii=False)}]
        result = await _bounded_model_input(CallModelData(
            model_data=ModelInputData(input=items, instructions="role"), agent=agents["manager"], context=self.context))
        self.assertEqual(json.loads(result.input[-1]["output"]), output)

    async def test_investigator_returns_real_registered_material_to_analysis(self):
        wrapper = SimpleNamespace(context=self.context)
        result = SimpleNamespace(tool=SimpleNamespace(name="read_review_passage"),
                                 output=json.dumps({"passage_id": "p", "text": "真实设计原文。"}))
        self.assertTrue((await _terminal_tool_completion(wrapper, [result])).is_final_output)
        result.output = json.dumps({"error_code": "checkset_not_finalized", "execution_status": "blocked"})
        self.assertFalse((await _terminal_tool_completion(wrapper, [result])).is_final_output)

    def test_required_nested_failure_is_persisted_as_terminal_execution_error(self):
        with self.assertRaisesRegex(RuntimeError, "specialist_execution_failed"):
            _fatal_nested_failure(SimpleNamespace(context=self.context, tool_name="investigate_review_material"),
                                  RuntimeError("Max turns (12) exceeded"))
        marker = self.context.store.data["terminal_tool_error"]
        self.assertEqual(marker["error_code"], "specialist_execution_failed")
        self.assertIn("Max turns", marker["message"])

    async def test_sdk_hides_investigation_until_extraction_is_finalized(self):
        workspace = await self.context.client.get("/workspace")
        workspace["sentences"][0]["checks_finalized"] = False
        agents = _build_agents("unused", {}, self.context)
        wrapper = SimpleNamespace(context=self.context)
        with patch("software_quality_agent.review_runtime.control._workspace", new=AsyncMock(return_value=workspace)):
            names = {tool.name for tool in await agents["analysis"].get_all_tools(wrapper)}
            self.assertNotIn("read_review_passage", names)
            self.assertNotIn("investigate_review_material", names)
            self.assertIn("create_review_check", names)
            self.assertIn("get_mandatory_tlr_nodes", names)
            self.assertIn("get_tlr_candidates", names)
            self.assertIn("get_canonical_node", names)
            workspace["sentences"][0]["checks_finalized"] = True
            names = {tool.name for tool in await agents["analysis"].get_all_tools(wrapper)}
            self.assertIn("read_review_passage", names)

    async def test_source_cannot_be_registered_as_design_evidence_and_error_is_actionable(self):
        self.context.client = SimpleNamespace(get=AsyncMock(return_value=
            {"artifact_id": "source-artifact", "text": "需求原文。"}), write=AsyncMock())
        self.context.bound_target_artifact_ids = ("target-artifact",)
        arguments = json.dumps({"node_id": "source-node", "start_offset": 0,
                                "text_limit": 5, "candidate_id": None})
        context = ToolContext(context=self.context, tool_name="read_review_passage",
                              tool_call_id="source-read", tool_arguments=arguments,
                              run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await read_review_passage.on_invoke_tool(context, arguments))
        self.assertEqual(result["execution_status"], "read_only")
        self.assertFalse(result["canonical_evidence"])
        self.assertIsNone(result["passage_id"])
        self.context.client.write.assert_not_awaited()

    async def test_unfinalized_checks_reject_read_without_a_fake_passage(self):
        workspace = await self.context.client.get("/workspace")
        workspace["sentences"][0]["checks_finalized"] = False
        self.context.client = SimpleNamespace(get=AsyncMock(side_effect=[
            {"artifact_id": "target-artifact", "text": "设计原文。"}, workspace]), write=AsyncMock())
        arguments = json.dumps({"node_id": "design-node", "start_offset": 0,
                                "text_limit": 5, "candidate_id": None})
        context = ToolContext(context=self.context, tool_name="read_review_passage",
                              tool_call_id="early-read", tool_arguments=arguments,
                              run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await read_review_passage.on_invoke_tool(context, arguments))
        self.assertEqual(result["error_code"], "checkset_not_finalized")
        self.assertNotIn("passage_id", result)
        self.context.client.write.assert_not_awaited()

    async def test_valid_target_still_uses_backend_registration_and_exact_range(self):
        workspace = await self.context.client.get("/workspace")
        self.context.client = SimpleNamespace(get=AsyncMock(side_effect=[
            {"artifact_id": "target-artifact", "text": "设计原文。", "has_more_text": False}, workspace]),
            write=AsyncMock(return_value={"passage_id": "registered"}))
        self.context.bound_target_artifact_ids = ("target-artifact",)
        arguments = json.dumps({"node_id": "other-design-node", "start_offset": 7,
                                "text_limit": 5, "candidate_id": "candidate"})
        context = ToolContext(context=self.context, tool_name="read_review_passage",
                              tool_call_id="valid-read", tool_arguments=arguments,
                              run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await read_review_passage.on_invoke_tool(context, arguments))
        self.assertEqual(result["passage_id"], "registered")
        payload = self.context.client.write.await_args.args[2]
        self.assertEqual(payload["start_offset"], 7)
        self.assertEqual(payload["end_offset"], 12)
        self.assertEqual(payload["candidate_id"], "candidate")

    async def test_context_trimming_keeps_real_unopened_target_id_without_inventing_evidence(self):
        self.context.bound_run_id = "run"
        self.context.bound_source_node_id = "source"
        self.context.store.data["sdk_tool_results"] = {
            "real-query": {"tool": "get_mandatory_tlr_nodes", "output": {
                "run_id": "run", "source_node_id": "source", "items": [
                    {"node_id": "opened", "candidate_id": "old-candidate"},
                    {"node_id": "next-target", "candidate_id": "next-candidate"}]}},
            "foreign-query": {"tool": "get_mandatory_tlr_nodes", "output": {
                "run_id": "other-run", "source_node_id": "source", "items": [
                    {"node_id": "foreign", "candidate_id": "foreign-candidate"}]}}}
        workspace = await self.context.client.get("/workspace")
        workspace["passages"] = []
        workspace["visits"] = [{"design_node_id": "opened"}]
        with patch("software_quality_agent.review_runtime.model_input._workspace", new=AsyncMock(return_value=workspace)):
            agents = _build_agents("unused", {}, self.context)
            result = await _bounded_model_input(CallModelData(
                model_data=ModelInputData(input=[{"role": "user", "content": "task"}], instructions="role"),
                agent=agents["analysis"], context=self.context))
        snapshot = json.loads(result.input[1]["content"].split(": ", 1)[1])
        reference = snapshot["unopened_mandatory_reference"]
        self.assertEqual(reference["target_node_id"], "next-target")
        self.assertEqual(reference["candidate_id"], "next-candidate")
        self.assertEqual(reference["retrieved_from"], {"call_id": "real-query", "field_path": ["items", "1"]})
        self.assertNotIn("evidence_id", reference)
        workspace["passages"] = [{"sentence_id": "s", "design_node_id": "next-target", "status": "blocked"}]
        self.assertIsNone(_unopened_mandatory_reference(self.context, workspace))

    async def test_truncated_provider_tool_call_is_blocked_before_sdk_can_execute_it(self):
        response = httpx.Response(200, json={"id": "fixture", "choices": [{"index": 0,
            "finish_reason": "length", "message": {"content": None,
            "reasoning_content": "private-do-not-save", "tool_calls": [{"id": "tool",
            "type": "function", "function": {"name": "assess_review_passage",
                                                "arguments": '{"passage_id":"p"}'}}]}}]},
            request=httpx.Request("POST", "http://local-model/v1/chat/completions"))
        async def parent_response(*args, **kwargs):
            await _observe_provider_response(self.context.store, response)
            return ModelResponse(output=[ResponseFunctionToolCall(type="function_call", call_id="tool",
                name="assess_review_passage", arguments='{"passage_id":"p"}')],
                usage=Usage(requests=1, output_tokens=512), response_id="fixture")
        model = ObservedChatCompletionsModel(store=self.context.store, model="unused", openai_client=None)
        with patch("agents.models.openai_chatcompletions.OpenAIChatCompletionsModel.get_response",
                   new=parent_response), self.assertRaisesRegex(ModelBehaviorError, "provider_output_truncated"):
            await model.get_response()
        record = self.context.store.data["model_calls"][0]
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["provider_response"]["finish_reasons"], ["length"])
        self.assertNotIn("private-do-not-save", json.dumps(record))
        self.assertEqual(len(self.context.store.data["model_calls"]), 1)

    async def test_native_request_observer_preserves_public_contract_without_secrets_or_mutation(self):
        self.context.store.data["model_calls"] = [{"status": "running"}]
        payload = {"model": "local", "tool_choice": "required", "parallel_tool_calls": False,
                   "max_tokens": 1536, "tools": [{"type": "function", "function": {"name": "next"}}],
                   "chat_template_kwargs": {"enable_thinking": False},
                   "api_key": "private-key", "reasoning_content": "private-thinking",
                   "messages": [{"role": "assistant", "content": "public note",
                                 "reasoning_content": "private-message-thinking"}]}
        request = httpx.Request("POST", "http://local-model/v1/chat/completions",
                                json=payload, headers={"Authorization": "private-authorization"})
        original = request.content
        await _observe_provider_request(self.context.store, request)
        saved = self.context.store.data["model_calls"][-1]["provider_request"]
        self.assertEqual(request.content, original)
        self.assertEqual(saved["tools"], payload["tools"])
        self.assertEqual(saved["messages"], [{"role": "assistant", "content": "public note"}])
        self.assertFalse(saved["parallel_tool_calls"])
        self.assertFalse(saved["chat_template_kwargs"]["enable_thinking"])
        self.assertNotIn("private", json.dumps(saved))

    async def test_read_only_workspace_tools_record_exact_success_without_changing_business_revision(self):
        self.context.store.note("investigation", "public note", ["node"])
        self.context.store.data["suggestion_drafts"] = [{"iteration": 1, "suggestion_text": "existing"}]
        revision = self.context.store.data.get("facts_revision", 0)
        for tool, arguments in ((get_work_notes, {"offset": 0, "limit": 1}),
                                (get_suggestion_workspace, {"draft_offset": 0, "feedback_offset": 0, "limit": 1})):
            encoded = json.dumps(arguments)
            ctx = ToolContext(context=self.context, tool_name=tool.name,
                              tool_call_id="read-" + tool.name, tool_arguments=encoded,
                              run_config=RunConfig(tracing_disabled=True))
            result = json.loads(await tool.on_invoke_tool(ctx, encoded))
            call = self.context.store.data["tool_calls"][-1]
            self.assertEqual(call["name"], tool.name)
            self.assertTrue(call["succeeded"])
            self.assertEqual(call["output"], result)
        self.assertEqual(self.context.store.data.get("facts_revision", 0), revision)
        self.assertEqual(self.context.store.data["tool_errors"], [])

    async def test_cancelled_model_call_does_not_remain_running(self):
        model = ObservedChatCompletionsModel(store=self.context.store, model="unused", openai_client=None)
        with patch("agents.models.openai_chatcompletions.OpenAIChatCompletionsModel.get_response",
                   new=AsyncMock(side_effect=asyncio.CancelledError)), self.assertRaises(asyncio.CancelledError):
            await model.get_response()
        record = self.context.store.data["model_calls"][0]
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["error_code"], "worker_interrupted")

    async def test_provider_observer_is_wired_without_changing_timeout_or_retry(self):
        model, client = _model_for(SimpleNamespace(suggestion_base_url="http://local-model/v1",
            suggestion_api_key="fixture-only", suggestion_model="unused"), self.context.store)
        try:
            self.assertIsInstance(model, ObservedChatCompletionsModel)
            self.assertEqual(client.max_retries, 0)
            self.assertEqual(client.timeout, 180.0)
            self.assertEqual(len(client._client.event_hooks["request"]), 1)
            self.assertEqual(len(client._client.event_hooks["response"]), 1)
        finally:
            await client.close()

    async def test_sdk_invalid_json_and_missing_fields_fail_before_business_execution(self):
        self.context.client = SimpleNamespace(get=AsyncMock(), write=AsyncMock())
        for arguments in ("not-json", '{"passage_id":"existing"}'):
            context = ToolContext(context=self.context, tool_name="assess_review_passage",
                                  tool_call_id="invalid", tool_arguments=arguments,
                                  run_config=RunConfig(tracing_disabled=True))
            with self.assertRaisesRegex(ModelBehaviorError, "invalid_tool_arguments"):
                await assess_review_passage.on_invoke_tool(context, arguments)
        self.context.client.get.assert_not_awaited()
        self.context.client.write.assert_not_awaited()
        self.assertEqual(len(self.context.store.data["tool_errors"]), 2)
        self.assertEqual(self.context.store.data["tool_calls"][-1]["arguments"]["raw_sdk_arguments"],
                         '{"passage_id":"existing"}')

    async def test_per_check_passage_tool_keeps_model_arguments_small(self):
        agents = _build_agents("unused", {}, self.context)
        schemas = {tool.name: tool.params_json_schema for tool in agents["analysis"].tools}
        self.assertIn("check_id", schemas["assess_review_check"]["properties"])
        self.assertIn("exact_quotes", schemas["assess_review_check"]["properties"])
        self.assertNotIn("decisions", schemas["assess_review_check"]["properties"])
        self.assertIn("passage_id", schemas["finalize_review_passage"]["properties"])

    async def test_finalize_passage_without_saved_decisions_is_execution_block(self):
        context = ToolContext(context=self.context, tool_name="finalize_review_passage",
                              tool_call_id="finalize", tool_arguments='{"passage_id":"passage"}',
                              run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await finalize_review_passage.on_invoke_tool(
            context, '{"passage_id":"passage"}'))
        self.assertEqual(result["execution_status"], "blocked")
        self.assertEqual(result["error_code"], "passage_has_no_saved_assessments")

    async def test_finalize_passage_retains_exact_saved_offsets(self):
        workspace = await self.context.client.get("/workspace")
        workspace["evidence"] = [{"evidence_id": "e", "check_id": "c1", "design_node_id": "design",
                                  "exact_quote": "设计原文", "start_offset": 0, "end_offset": 4,
                                  "validation_status": "valid"}]
        workspace["passages"][0]["assessments"] = [{"check_id": "c1", "relation": "supporting",
            "resulting_status": "supported", "note": "原文实现此检查点", "evidence_ids": ["e"]}]
        self.context.client = SimpleNamespace(get=AsyncMock(return_value=workspace),
                                              write=AsyncMock(return_value={"passage_status": "completed"}))
        context = ToolContext(context=self.context, tool_name="finalize_review_passage",
                              tool_call_id="finalize", tool_arguments='{"passage_id":"passage"}',
                              run_config=RunConfig(tracing_disabled=True))
        await finalize_review_passage.on_invoke_tool(context, '{"passage_id":"passage"}')
        quote = self.context.client.write.await_args.args[2]["decisions"][0]["quotes"][0]
        self.assertEqual(quote, {"exact_quote": "设计原文", "start_offset": 0, "end_offset": 4})

    async def test_finalize_already_completed_passage_is_read_only(self):
        workspace = await self.context.client.get("/workspace")
        workspace["passages"][0]["status"] = "completed"
        self.context.client = SimpleNamespace(get=AsyncMock(side_effect=[workspace, {"can_stop_for_sufficient_evidence": True}]),
                                              write=AsyncMock())
        context = ToolContext(context=self.context, tool_name="finalize_review_passage",
                              tool_call_id="finalize", tool_arguments='{"passage_id":"passage"}',
                              run_config=RunConfig(tracing_disabled=True))
        result = json.loads(await finalize_review_passage.on_invoke_tool(context, '{"passage_id":"passage"}'))
        self.assertTrue(result["already_completed"])
        self.assertTrue(result["can_stop_for_sufficient_evidence"])
        self.context.client.write.assert_not_awaited()

    async def test_identical_successful_state_change_is_replayable(self):
        payload = {"passage_id": "p", "decisions": [], "finalize": False}
        first = self.context.store.tool_call("assess_review_passage", payload)
        self.context.store.tool_success(first, {"passage_id": "p"})
        self.assertFalse(self.context.store.guard_replayed_write("assess_review_passage", payload))
        self.assertEqual(self.context.store.replayed_write_output("assess_review_passage", payload),
                         {"passage_id": "p"})
        self.assertIsNone(self.context.store.data["terminal_tool_error"])


if __name__ == "__main__":
    unittest.main()

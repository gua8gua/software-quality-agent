"""Check Chinese model-facing instructions without provider/network calls."""

import tempfile
import unittest
from pathlib import Path

from software_quality_agent.llm_admission import compact_authoritative_snapshot
from software_quality_agent.review_runtime.checkpoint import CheckpointStore
from software_quality_agent.review_runtime.context import SuggestionContext
from software_quality_agent.tool_definitions.common import _tool_error_feedback
from software_quality_agent.tool_definitions.saved_results import saved_result_index
from software_quality_agent.suggestion_workflow import _build_agents
from software_quality_agent.review_runtime.model_input import _passage_turn_budget


class ChinesePromptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.context = SuggestionContext(
            client=None, store=CheckpointStore(Path(self.directory.name), "review", "sentence"),
            project_id="project", review_id="review", sentence_id="sentence", tenant_id="local")

    def assert_chinese(self, text):
        self.assertRegex(text, r"[\u4e00-\u9fff]")

    def test_all_roles_and_their_tools_have_chinese_semantic_instructions(self):
        agents = _build_agents("unused-test-model", {}, self.context)
        self.assertEqual(set(agents), {"manager", "analysis", "evidence", "web", "suggestion", "validator"})
        for role, agent in agents.items():
            with self.subTest(role=role):
                self.assert_chinese(agent.instructions)
                self.assertIn("使用中文", agent.instructions)
                for tool in agent.tools:
                    self.assert_chinese(tool.description)
        self.assertIn("can_stop_for_sufficient_evidence", agents["analysis"].instructions)
        self.assertIn("CURRENT_STAGE", agents["analysis"].instructions)
        self.assertIn("candidate_id=null", agents["evidence"].instructions)

    def test_recovery_and_compaction_guidance_is_chinese_without_altering_ids(self):
        state = {"source_segment": {"text": "原始源语段"},
                 "all_checks": [{"check_id": "real-check", "status": "supported"}],
                 "saved_evidence_associations": []}
        compacted = compact_authoritative_snapshot(state)
        self.assert_chinese(compacted["compaction_instruction"])
        self.assertEqual(compacted["all_checks"][0]["check_id"], "real-check")
        self.assertEqual(compacted["all_checks"][0]["status"], "supported")
        index = saved_result_index("real-call", "read", {"items": ["原文"]})
        self.assert_chinese(index["instruction"])
        self.assertEqual(index["call_id"], "real-call")
        self.assert_chinese(_passage_turn_budget(self.context, "review analysis agent")["note"])

    def test_identifier_error_feedback_is_chinese_and_preserves_raw_error(self):
        cases = (("wrong Docling ref", "Docling"), ("invalid field_path", "field_path"),
                 ("outside current agent sentence", "check_id"), ("candidate mismatch", "candidate_id"))
        for message, expected_parameter in cases:
            with self.subTest(message=message):
                feedback = _tool_error_feedback("read_tool", ValueError(message))
                self.assert_chinese(feedback)
                self.assertIn("这是执行错误，不是语义结论", feedback)
                self.assertIn(message, feedback)
                self.assertIn(expected_parameter, feedback)


if __name__ == "__main__":
    unittest.main()

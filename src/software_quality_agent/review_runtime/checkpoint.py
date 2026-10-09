"""checkpoint definitions for the SDK review workflow."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .contracts import SuggestionDraft, SuggestionOutput, SuggestionValidation


class CheckpointStore:
    """Small public work log beside the SDK SQLite session.

    The Agents SDK session stores the model/tool transcript.  This JSON file
    stores only observable checkpoints and outputs so an operator can inspect
    progress without exposing hidden reasoning.
    """

    def __init__(self, root: Path, review_id: str, sentence_id: str):
        self.path = root / review_id / f"{sentence_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = {
            "schema_version": 7,
            "review_id": review_id,
            "sentence_id": sentence_id,
            "attempts": 0,
            "work_notes": [],
            "tool_errors": [],
            "tool_calls": [],
            "latest_output": None,
            "workflow_status": "pending",
            "stage": "dispatch",
            "current_review_phase": "load_source_segment",
            "current_review_next_action": "用 get_review_segment 读取完整源语段。",
            "agent_states": {},
            "stage_outputs": {},
            "errors": [],
            "paged_reads": {},
            "paged_read_cursors": {},
            "saved_page_replays": [],
            "terminal_tool_error": None,
            "attempt_id": None,
            "suggestion_drafts": [],
            "validation_feedback": [],
            "llm_admission": [],
            "llm_state": None,
            "model_failure_streak": 0,
            "model_preflight_failure_streak": 0,
            "truncation_continuations": 0,
            "agent_turn_bases": {},
            "tool_error_repeats": {},
        }
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if (
                    not isinstance(loaded, dict)
                    or loaded.get("review_id") != review_id
                    or loaded.get("sentence_id") != sentence_id
                ):
                    raise ValueError("checkpoint identity or structure is invalid")
                self.data.update(loaded)
                self.data["schema_version"] = 7
            except (OSError, ValueError):
                # A corrupt checkpoint is recorded as a new blocked attempt by the caller;
                # no model result is fabricated from it.
                self.data["checkpoint_error"] = "checkpoint_json_unreadable"

    def _save(self) -> None:
        if self.data.get("checkpoint_error"):
            raise ValueError("checkpoint_json_unreadable: original checkpoint preserved")
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def begin_attempt(self) -> None:
        if self.data.get("checkpoint_error"):
            raise ValueError("checkpoint_json_unreadable: original checkpoint preserved")
        previous_attempt = int(self.data.get("attempts", 0))
        if previous_attempt:
            self.data.setdefault("attempt_history", []).append(
                {
                    "attempt": previous_attempt,
                    "attempt_id": self.data.get("attempt_id"),
                    "workflow_status": self.data.get("workflow_status"),
                    "stage": self.data.get("stage"),
                    "current_review_phase": self.data.get("current_review_phase"),
                    "current_review_next_action": self.data.get("current_review_next_action"),
                    "agent_states": self.data.get("agent_states", {}),
                    "stage_outputs": self.data.get("stage_outputs", {}),
                    "latest_output": self.data.get("latest_output"),
                    "errors": self.data.get("errors", []),
                    "tool_errors": self.data.get("tool_errors", []),
                    "tool_calls": self.data.get("tool_calls", []),
                    "model_calls": self.data.get("model_calls", []),
                    "sdk_tool_results": self.data.get("sdk_tool_results", {}),
                    "model_input_stats": self.data.get("model_input_stats", []),
                    "llm_admission": self.data.get("llm_admission", []),
                    "llm_state": self.data.get("llm_state"),
                    "model_failure_streak": self.data.get("model_failure_streak", 0),
                    "model_preflight_failure_streak": self.data.get(
                        "model_preflight_failure_streak", 0
                    ),
                    "truncation_continuations": self.data.get("truncation_continuations", 0),
                }
            )
        self.data["attempts"] = previous_attempt + 1
        self.data["workflow_status"] = "pending"
        self.data["stage"] = "dispatch"
        self.data["current_review_phase"] = "load_source_segment"
        self.data["current_review_next_action"] = "用 get_review_segment 读取完整源语段。"
        self.data["agent_states"] = {}
        self.data["stage_outputs"] = {}
        self.data["latest_output"] = None
        self.data["errors"] = []
        self.data["tool_errors"] = []
        self.data["tool_calls"] = []
        self.data["model_calls"] = []
        self.data["sdk_tool_results"] = {}
        self.data["model_input_stats"] = []
        self.data["llm_admission"] = []
        self.data["llm_state"] = None
        self.data["model_failure_streak"] = 0
        self.data["model_preflight_failure_streak"] = 0
        self.data["truncation_continuations"] = 0
        self.data["active_model_call_id"] = None
        self.data["agent_turn_bases"] = {}
        self.data["tool_error_repeats"] = {}
        self.data["last_business_progress_at"] = datetime.now(UTC).isoformat()
        self.data["progress_keys"] = []
        self.data["paged_reads"] = {}
        self.data["paged_read_cursors"] = {}
        self.data["saved_page_replays"] = []
        self.data["terminal_tool_error"] = None
        self.data["investigation_replay"] = {}
        self.data["attempt_id"] = f"attempt-{self.data['attempts']}"
        self.data["last_started_at"] = datetime.now(UTC).isoformat()
        self._save()

    def transition(
        self,
        stage: str,
        status: str,
        output: Any = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Persist a public state transition before the next SDK call.

        This is intentionally separate from the Agents SDK transcript: a
        process restart can resume from these stage records without asking the
        model to remember what happened in a previous conversation.
        """
        self.data["stage"] = stage
        self.data["workflow_status"] = status
        state = {"status": status, "updated_at": datetime.now(UTC).isoformat()}
        if error_code:
            state["error_code"] = error_code
        if error_message:
            state["error_message"] = error_message[:2000]
            self.data.setdefault("errors", []).append(
                {
                    "stage": stage,
                    "error_code": error_code,
                    "message": error_message[:2000],
                    "at": state["updated_at"],
                }
            )
        if output is not None:
            value = output.model_dump(mode="json") if isinstance(output, BaseModel) else output
            self.data.setdefault("stage_outputs", {})[stage] = value
            state["output_recorded"] = True
        self.data.setdefault("agent_states", {})[stage] = state
        self._save()

    def stage_complete(self, stage: str) -> bool:
        return self.data.get("agent_states", {}).get(stage, {}).get("status") == "completed"

    def tool_call(self, name: str, arguments: dict[str, Any]) -> int:
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.data.setdefault("tool_calls", []).append(
            {
                "at": datetime.now(UTC).isoformat(),
                "name": name,
                "arguments": arguments,
                "arguments_json": encoded,
                "succeeded": False,
            }
        )
        self._save()
        return len(self.data["tool_calls"]) - 1

    def tool_success(self, call_index: int, output: Any = None) -> None:
        self.data["tool_calls"][call_index]["succeeded"] = True
        name = self.data["tool_calls"][call_index].get("name")
        if name in {
            "create_review_check",
            "finalize_review_checks",
            "assess_review_check",
            "finalize_review_passage",
            "complete_review_analysis",
            "propose_review_assessment",
            "validate_review_assessment",
            "save_suggestion_draft",
            "save_suggestion_validation",
        }:
            self.data["facts_revision"] = int(self.data.get("facts_revision", 0)) + 1
        if output is not None:
            self.data["tool_calls"][call_index]["output"] = output

        key = hashlib.sha256(
            json.dumps(
                [name, self.data["tool_calls"][call_index].get("arguments"), output],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        keys = self.data.setdefault("progress_keys", [])
        if key not in keys:
            keys.append(key)
            self.data["last_business_progress_at"] = datetime.now(UTC).isoformat()
        self._save()

    def tool_error(self, name: str, message: str) -> None:
        self.data.setdefault("tool_errors", []).append(
            {
                "at": datetime.now(UTC).isoformat(),
                "name": name,
                "message": message[:2000],
            }
        )
        self._save()

    def guard_replayed_write(self, name: str, arguments: dict[str, Any]) -> bool:
        """Detect an identical successful state-changing tool replay.

        Reads are intentionally excluded: re-reading durable facts is safe.
        A byte-for-byte replay of a write (or the same passage assessment)
        cannot add evidence.  Callers return the saved response for a replay;
        only a replay with no saved response is treated as an execution error.
        """
        replayable = {
            "finalize_review_checks",
            "assess_review_passage",
            "assess_review_check",
            "finalize_review_passage",
            "complete_review_analysis",
            "propose_review_assessment",
            "validate_review_assessment",
            "save_suggestion_draft",
            "save_suggestion_validation",
        }
        if name not in replayable:
            return True
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for call in self.data.get("tool_calls", []):
            if (
                call.get("name") == name
                and call.get("succeeded")
                and (
                    call.get("arguments_json")
                    or json.dumps(
                        call.get("arguments", {}),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                == encoded
            ):
                self.data.setdefault("replayed_writes", []).append(
                    {
                        "tool": name,
                        "arguments": arguments,
                        "at": datetime.now(UTC).isoformat(),
                    }
                )
                self._save()
                return False
        return True

    def replayed_write_output(self, name: str, arguments: dict[str, Any]) -> Any:
        """Return the durable response for an already-successful write.

        A model/tool response can be lost after the backend committed.  The
        old implementation converted the next identical call into a fatal
        error, even though replaying the same write was safe.  Returning the
        saved response makes the operation idempotent without creating a
        duplicate fact or inventing a semantic result.
        """
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for call in reversed(self.data.get("tool_calls", [])):
            if (
                call.get("name") == name
                and call.get("succeeded")
                and (
                    call.get("arguments_json")
                    or json.dumps(
                        call.get("arguments", {}),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                == encoded
            ):
                return call.get("output")
        return None

    def guard_saved_page(
        self, call_id: str, field_path: list[str], offset: int, limit: int
    ) -> bool:
        """Record a saved-result page read and report whether it was replayed.

        Saved tool results are immutable read-only facts.  A model may need to
        revisit an earlier page after inspecting another field, so a repeated
        or backward page must not be treated as a state-changing error.  The
        caller marks the returned page as ``already_read`` to steer the model
        forward while preserving the exact value.  History is retained for
        diagnostics and resume, but never converted into a semantic result or
        a fabricated evidence record.
        """
        key = json.dumps([call_id, field_path], ensure_ascii=False, separators=(",", ":"))
        history = self.data.setdefault("paged_reads", {}).setdefault(key, [])
        signature = [int(offset), int(limit)]
        repeated = signature in history or bool(
            history and int(offset) < max(item[0] for item in history)
        )
        history.append(signature)
        self._save()
        if repeated:
            self.data.setdefault("saved_page_replays", []).append(
                {
                    "call_id": call_id,
                    "field_path": field_path,
                    "offset": offset,
                    "limit": limit,
                }
            )
            self._save()
        return repeated

    def note(self, step: str, text: str, references: list[str]) -> str:
        note_id = f"note-{len(self.data.setdefault('work_notes', [])) + 1}"
        self.data["work_notes"].append(
            {
                "note_id": note_id,
                "at": datetime.now(UTC).isoformat(),
                "step": step,
                "text": text[:4000],
                "references": references[:50],
            }
        )
        self._save()
        return note_id

    def notes(self) -> list[dict[str, Any]]:
        return list(self.data.get("work_notes", []))

    def save_draft(self, draft: SuggestionDraft) -> dict[str, Any]:
        record = {
            "iteration": len(self.data.setdefault("suggestion_drafts", [])) + 1,
            "at": datetime.now(UTC).isoformat(),
            **draft.model_dump(mode="json"),
        }
        self.data["suggestion_drafts"].append(record)
        self.data["stage"] = "suggestion_draft_saved"
        self._save()
        return record

    def save_validation(self, feedback: SuggestionValidation) -> dict[str, Any]:
        drafts = self.data.get("suggestion_drafts", [])
        if not drafts:
            raise ValueError("cannot validate before a suggestion draft is saved")
        record = {
            "draft_iteration": drafts[-1]["iteration"],
            "at": datetime.now(UTC).isoformat(),
            **feedback.model_dump(mode="json"),
        }
        self.data.setdefault("validation_feedback", []).append(record)
        self.data["stage"] = "suggestion_validation_saved"
        self._save()
        return record

    def output(self, value: SuggestionOutput) -> None:
        # Bind the public result to the checkpoint attempt.  The backend batch
        # endpoint uses this monotonically increasing number to ignore late
        # responses from an older worker after resume.
        if value.attempt is None:
            value.attempt = int(self.data.get("attempts", 0))
        if value.attempt_id is None:
            value.attempt_id = self.data.get("attempt_id")
        # SDK on_end is not called on exceptions. Close every still-running
        # public lifecycle record; this only fixes execution bookkeeping and
        # never changes semantic check statuses.
        close_status = "blocked" if value.execution_status == "blocked" else "completed"
        for stage, state in list(self.data.get("agent_states", {}).items()):
            if state.get("status") == "running":
                self.transition(
                    stage,
                    close_status,
                    error_code=value.error_code if close_status == "blocked" else None,
                    error_message=value.error_message if close_status == "blocked" else None,
                )
        self.data["latest_output"] = value.model_dump(mode="json")
        self.data["workflow_status"] = value.execution_status
        self.data["stage"] = "completed" if value.execution_status != "blocked" else "blocked"
        self.data["last_finished_at"] = datetime.now(UTC).isoformat()
        self._save()

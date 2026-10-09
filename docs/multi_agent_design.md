# TLR-bound review and suggestion route

This is the current code path, not a claim that the local model has completed a full real review. A completed TLR run and one requirement canonical node are bound by the backend review workspace. The backend prepares one exact source-node range and provides deterministic information and write tools. All review cognition is delegated to OpenAI Agents SDK `Runner`; the backend review route does not call `LLMProvider.chat_json`.

## SDK roles

| Role | Responsibility | Principal tools |
|---|---|---|
| Manager | Dispatch review, suggestion and validation; decide when to stop | Specialist `Agent.as_tool`, workspace reads |
| Review Analysis | Generate source-anchored checks, inspect mandatory TLR nodes once, investigate each check, persist evidence and status | Review reads/writes, mandatory pages, Evidence Investigator |
| Evidence Investigator | Investigate one check; return factual node IDs, quotes, gaps and scope, never a verdict | Existing TLR, canonical tree, artifact and bounded BM25 tools |
| Web Research | Optional external standards/papers/projects context; never canonical evidence | SDK function tools wrapping `ddgs` search and page extraction |
| Suggestion | Read all persisted review facts; save and revise one suggestion draft | Review/canonical/artifact reads, draft write, optional Web Research |
| Suggestion Validator | Check draft coverage, grounding and uncertainty; save revision feedback | Review/canonical reads, validation write |

All six roles are actual SDK `Agent` objects. Agents use `output_type=str` because the tested local Qwen endpoint has not reliably combined tool calls with strict final JSON. This is not a fallback LLM path: typed SDK function tools immediately persist structured business facts, and SDK output guardrails reject textual claims of completion when those facts are absent. The public `SuggestionOutput` is a deterministic projection of the persisted, validated workspace, not a separate model-generated finalizer.

## One sentence workflow

`prepare` binds the completed TLR and creates one exact source range. Review Analysis reads that range, creates `function_result` and `condition_constraint` checks from unique exact source quotes, reads mandatory TLR candidates in bounded canonical-text pages, records visited IDs, delegates focused per-check investigation, and persists exact evidence and check verdicts. It must call `complete_review_analysis`; its SDK output guardrail rejects an early prose-only finish. Execution errors leave checks pending and block completion; `insufficient` and `uncertain` are semantic judgments, not error fallbacks.

After verified review completion, Manager may invoke Suggestion, then Validator, with at most three revision instructions. Draft and feedback are durable checkpoint objects; each specialist's output guardrail requires a new persisted draft or feedback record. Manager and final projection reject missing checks, missing mandatory visits, missing supporting/counter evidence, wrong IDs/quotes and absent validation. No specialist edits canonical content or reruns TLR.

The SDK SQLite session stores the transcript. Backend review tables store source ranges, checks, evidence, visits, tasks and events; the frontend JSON checkpoint stores agent stage states, tool-call/error log, work notes, suggestion drafts and validation feedback. The SDK input filter keeps exact history until the tokenizer admission gate requires compaction; only then does the workflow create saved-result pointers and retain a bounded recent tool loop, while durable facts remain retrievable by ID. Review Analysis follows an explicit material-driven phase protocol (`READ_SOURCE -> EXTRACT_CHECKS -> SELECT_ONE_SDS_PASSAGE -> ASSESS_ALL_CHECKS -> FINALIZE_PASSAGE -> CONCLUDE_CHECKS -> PROPOSE_OVERALL`); investigation tools return `current_stage` and `next_required_action`, and specialist exits report the same phase to the Manager. A failed run is recorded as `blocked`, never as a successful review.

## Verified boundary

Real attempts on 2026-10-02 used existing completed TLR run `55f34d70-d38d-49e3-94d1-f01fe92c00d7` and requirement node `3b470435-ea9c-477d-b391-1741fd3bce73`. The local Qwen3.5-9B did not complete the full tool lifecycle: observed failures included context overflow, Evidence Investigator turn exhaustion and Review Analysis ending in prose before persisting checks. The SDK route and guardrails are implemented, but full end-to-end review/suggestion correctness remains unverified. See `日志/2026-10-02_审核Agent单轨重构与真实运行报告.md` for the exact attempts and remaining limitations.

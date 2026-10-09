"""Deterministic business boundary shared by tools and SDK routing.

This is not a replacement Agent loop: Runner invokes specialists/tools. The
policy only decides which persisted transition is currently legal.
"""

def suggestion_phase(data: dict, assessment: dict, budget: int) -> str:
    if not assessment.get("finalized") or not assessment.get("suggestion_required"):
        return "not_needed"
    drafts = [d for d in data.get("suggestion_drafts", [])
              if d.get("assessment_fingerprint") == assessment.get("proposal_fingerprint")]
    if not drafts:
        return "draft"
    feedback = next((f for f in reversed(data.get("validation_feedback", []))
                     if f.get("draft_iteration") == drafts[-1]["iteration"]), None)
    if feedback is None:
        return "validate"
    if feedback.get("valid"):
        return "complete"
    return "exhausted" if len(drafts) >= budget else "draft"

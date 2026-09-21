import uuid


def new_state():
    """Create a fresh state for one request."""
    return {
        "request_id": str(uuid.uuid4()),
        "request_received": False,
        "request_classified": False,
        "authorized": None,          # None means "not judged yet".
        "analysis_done": False,
        "result": None,
        "answered": False,
        "rejection_reason": None,
        "finished": False,
        "policy_override": None,
        "history": [],

        # Request decomposition
        "request_parts": [],
        "denied_parts": [],
        "question_to_run": None,
        "classifier_error": False,

        # Column mapping
        "map_stage_failure": None,

        # Raw model output and repair attempts
        "column_map": None,
        "map_attempts": [],
        "code_attempts": [],
    }


def state_for_llm(state):
    """Return only the state fields needed for the next action."""
    return {
        "request_classified": state["request_classified"],
        "authorized": state["authorized"],
        "analysis_done": state["analysis_done"],
        "answered": state["answered"],
    }
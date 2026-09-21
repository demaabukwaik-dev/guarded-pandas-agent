def _apply_policy(action, state):

    # Classification must happen before rejecting or analyzing.
    if action == "reject_request" and not state["request_classified"]:
        state["policy_override"] = (
            "reject_request → classify_request (not classified yet)"
        )
        return "classify_request"

    if action == "run_analysis" and not state["request_classified"]:
        state["policy_override"] = (
            "run_analysis → classify_request (not classified yet)"
        )
        return "classify_request"

    # Never analyze a request that was classified as unauthorized.
    if action == "run_analysis" and state["authorized"] is False:
        state["policy_override"] = (
            "run_analysis → reject_request (unauthorized)"
        )
        return "reject_request"

    # An answer requires a completed analysis result.
    if action == "answer_user" and state["result"] is None:
        state["policy_override"] = (
            "answer_user → run_analysis (no result yet)"
        )
        return "run_analysis"

    # The workflow cannot finish before answering or rejecting.
    if action == "finish" and not (state["answered"] or state["rejection_reason"]):
        state["policy_override"] = (
            "finish → classify_request (nothing done yet)"
        )
        return "classify_request"

    # Do not repeat a successful analysis.
    if action == "run_analysis" and state["result"] is not None:
        state["policy_override"] = (
            "run_analysis → answer_user (analysis already done)"
        )
        return "answer_user"

    # Do not answer more than once.
    if action == "answer_user" and state["answered"]:
        state["policy_override"] = (
            "answer_user → finish (already answered)"
        )
        return "finish"

    # Do not classify a request that is already classified.
    if action == "classify_request" and state["request_classified"]:
        if state["authorized"] is False:
            state["policy_override"] = (
                "classify_request → reject_request (already classified, unauthorized)"
            )
            return "reject_request"

        state["policy_override"] = (
            "classify_request → run_analysis (already classified)"
        )
        return "run_analysis"

    return action


def enforce_policy(action, state, max_passes=6):
    """Apply policy rules until the action is stable or the pass limit is reached."""

    for _ in range(max_passes):

        new_action = _apply_policy(action, state)

        if new_action == action:
            return action

        action = new_action

    # Conflicting rules must not leave the workflow in an unknown state.
    state["policy_override"] = "unstable policy resolution → reject_request"
    return "reject_request"
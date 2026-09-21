import pandas as pd
import time

from agent.llm import ask_llm
from agent.parsing import extract_json
from agent.config import MAX_DECISION_ATTEMPTS, MAX_STEPS, ALLOWED_ACTIONS
from agent.prompts.decision import build_decision_prompt
from agent.classify import classify_request
from agent.codegen import run_code_agent_with_retry
from agent.present import format_result
from agent.state import new_state
from agent.policy import enforce_policy
from agent.guards import PolicyViolation
from agent.mapping import MapStageFailure
from agent.parsing import ExtractionFailure


def validate_action(action):
    """Check whether the model returned a valid action."""
    return action in ALLOWED_ACTIONS


def decide(question, state, max_attempts=MAX_DECISION_ATTEMPTS, verbose=False):
    """Ask the model for an action, retrying when the output is invalid."""

    # Reset attempts for this decision so old attempts are not mixed with new ones.
    state["_decision_attempts"] = []
    error = None

    for _ in range(max_attempts):

        messages = build_decision_prompt(question, state, error)
        raw = ask_llm(messages)
        state["_decision_attempts"].append(raw)

        if verbose:
            print(f"       LLM raw: {raw}")

        try:
            decision = extract_json(raw)
        except Exception:
            error = "output was not valid JSON."
            print("        decision retry — output was not valid JSON")
            continue

        action = decision.get("action")

        if not validate_action(action):
            error = f"'{action}' is not an allowed action."
            print(f"        decision retry — '{action}' is not an allowed action")
            continue

        return decision

    return None


def execute_action(action, state, df, question):

    if action == "classify_request":
        classify_request(question, state)

    elif action == "run_analysis":
        target = state["question_to_run"] or question
        state["result"] = run_code_agent_with_retry(target, df, state)
        state["analysis_done"] = True

    elif action == "reject_request":
        if not state["rejection_reason"]:
            state["rejection_reason"] = "Request not permitted."
        print("\n       Request Rejected – Unauthorized Query")
        print(f"         {state['rejection_reason']}")
        state["finished"] = True

    elif action == "answer_user":
        print(f"\n       Raw result: {state['result']}")
        print(f"       {format_result(state['question_to_run'] or question, state['result'])}")

        if state["denied_parts"]:
            print("\n       Not executed:")
            for p in state["denied_parts"]:
                print(f"         - {p['text']}  ({p['reason']})")

        state["answered"] = True

    elif action == "finish":
        state["finished"] = True

    return state




def _log_step(state, step, raw_action, action):
    """Record the model's action, final action, overrides, and decision attempts."""
    state["history"].append({
        "step": step + 1,
        "llm_action": raw_action,
        "final_action": action,
        "override": state["policy_override"],
        "decision_attempts": state.pop("_decision_attempts", []),
    })


# Exceptions that should stop the workflow and be displayed to the users.
_STOPS = (
    (PolicyViolation,   None),
    (MapStageFailure,   None),
    (ExtractionFailure, "Could not produce runnable code for this question. "
                        "Please rephrase it."),
    (RuntimeError,      "Could not compute safely: {error}"),
)


def _handle_stop(state, exc, verbose):
    """Record a stop and end the run. Returns False when the exception is
    not one the loop handles, so the caller re-raises it."""
    for exc_type, template in _STOPS:
        if not isinstance(exc, exc_type):
            continue

        state["rejection_reason"] = (
            str(exc) if template is None else template.format(error=exc)
        )
        if isinstance(exc, MapStageFailure):
            # Store which mapping stage failed.
            state["map_stage_failure"] = type(exc).__name__
        state["finished"] = True

        if verbose:
            print(f"\n       {type(exc).__name__}: {exc}")
        return True

    return False



def print_run_summary(state):
    overrides = sum(
        1 for h in state["history"]
        if h["override"]
    )

    print("\n   ── Run Summary ──")
    print(f"   request_id: {state['request_id']}")
    print(f"   steps: {len(state['history'])}")
    print(f"   policy overrides: {overrides}")
    print(f"   mapping attempts: {len(state['map_attempts'])}")
    print(f"   code attempts: {len(state['code_attempts'])}")
    print(f"   duration: {state['duration_seconds']:.2f}s")
    print(f"   answered: {state['answered']}")


def run_agent(question, df, verbose=True):

    state = new_state()
    start = time.perf_counter() 
    state["request_received"] = True

    if verbose:
        print("\n" + "=" * 62)
        print(f" {question}")
        print("=" * 62)

    for step in range(MAX_STEPS):

        decision = decide(question, state)

        if decision is None:
            # Keep failed decision attempts in the history for diagnosis.
            _log_step(state, step, None, None)
            state["rejection_reason"] = "Invalid decision from model."
            state["finished"] = True
            if verbose:
                print("\n    Model failed to produce a valid decision.")
            break

        raw_action = decision["action"]
        state["policy_override"] = None
        action = enforce_policy(raw_action, state)

        if verbose:
            print(f"\n   ── Step {step + 1} " + "─" * 40)
            print(f"    LLM chose      : {raw_action}")
            if state["policy_override"]:
                print(f"     Policy override: {state['policy_override']}")
            print(f"    Executing      : {action}")

        _log_step(state, step, raw_action, action)

        # Keep stage failures in the state so the final run can be diagnosed.
        try:
            state = execute_action(action, state, df, question)
        
        except Exception as e:
            if not _handle_stop(state, e, verbose):
                raise
            break

        if state["finished"]:
            break

    # The loop may reach MAX_STEPS without finishing normally.
    if not state["finished"]:
        state["rejection_reason"] = (
            f"Workflow did not settle within {MAX_STEPS} steps."
        )
        state["finished"] = True

    state["duration_seconds"] = time.perf_counter() - start
        

    if verbose:
        overrides = sum(1 for h in state["history"] if h["override"])
        print("\n   " + "─" * 46)
        print(f"   steps: {len(state['history'])}   overrides: {overrides}   "
              f"answered: {state['answered']}")
        print("=" * 62)

    if verbose:
        print_run_summary(state)

    return state



def solve(question: str, df: pd.DataFrame, verbose=True):
    """Returns the result on success, or the rejection reason as a string."""

    state = run_agent(question, df, verbose=verbose)

    if state["rejection_reason"]:
        return state["rejection_reason"]

    if not state["answered"]:
        print("\n     Workflow ended without answering.")
        return "Could not complete this request."

    return state["result"]

from agent.llm import ask_llm
from agent.parsing import extract_json
from agent.prompts.classify import build_classify_prompt

# Phrases that always make a part unsafe.
DENY_PHRASES = [
    "all rows", "all records", "every transaction",
    "entire dataset", "full table", "raw data",
    "example order", "example record", "example transaction",
    "example row", "example customer",
    "sample row", "sample record", "sample order",
    "actual transaction", "actual order", "actual record",
]


def _ask_classifier(question):
    """Call the classifier and return its parts or an error."""

    try:
        raw = ask_llm(build_classify_prompt(question))
        print("\n       CLASSIFIER RAW OUTPUT:")
        print("      " + raw.replace("\n", "\n      "))
        return extract_json(raw)["parts"], None
    except Exception as e:
        print(f"       classifier error: {e}")
        return None, f"{type(e).__name__}: {e}"



def validate_parts(question, parts):
    """Deterministic validation of the classifier output contract."""

    if not isinstance(parts, list) or not parts:
        return False, "NO_PARTS: no parts returned"

    for p in parts:
        if not isinstance(p, dict):
            return False, "NOT_OBJECT: part is not an object"

        if not isinstance(p.get("text"), str) or not p["text"].strip():
            return False, "NO_TEXT: part has no text"

        if not isinstance(p.get("allowed"), bool):
            return False, "ALLOWED_TYPE: 'allowed' is not a boolean"

    return True, None


def _apply_deny_phrases(parts):
    """Override the model when a known unsafe phrase is detected."""
    for p in parts:
        hit = next((ph for ph in DENY_PHRASES if ph in p["text"].lower()), None)
        if hit and p["allowed"]:
            p["allowed"] = False
            p["reason"] = f"deny phrase: '{hit}'"
            print(f"        deny-phrase override on part: {p['text'][:50]!r}")


def _fail_closed(state, question, err):
    """Reject the request when the classifier output cannot be trusted."""

    state["classifier_error"] = True
    state["authorized"] = False
    state["request_parts"] = []
    state["denied_parts"] = [{"text": question, "allowed": False, "reason": err}]
    state["question_to_run"] = None
    state["rejection_reason"] = (
        "Could not analyse the request. Please rephrase it more clearly."
    )
    print(f"       classifier output failed : {err}")
    return state



def _derive_state(state, question, parts):
    """Build the final state and the text allowed to reach code generation."""
    state["request_parts"] = parts
    state["denied_parts"] = [p for p in parts if not p["allowed"]]
    state["authorized"] = any(p["allowed"] for p in parts)

    allowed_texts = [p["text"] for p in parts if p["allowed"]]

    if not allowed_texts:
        # Nothing safe remains, so no analysis is allowed.
        state["question_to_run"] = None
        state["rejection_reason"] = "; ".join(p["reason"] for p in parts)

    elif not state["denied_parts"]:
        # If nothing was removed, keep the original request unchanged.
        state["question_to_run"] = question
        state["rejection_reason"] = None

    else:
        # Run only the allowed parts.
        state["question_to_run"] = "\n".join(
            f"{i + 1}. {t}" for i, t in enumerate(allowed_texts)
        )
        state["rejection_reason"] = None


def _report(state, parts):
    """Print a short classification summary for debugging."""
    print(f"       split into {len(parts)} part(s) → "
          f"authorized = {state['authorized']}")
    for p in parts:
        mark = "[allow]" if p["allowed"] else "[deny] "
        print(f"         {mark} {p['text'][:60]}  — {p['reason']}")


def classify_request(question, state):
    """Split the request, judge each part, and derive the state. Two
    deterministic guards sit around the model: validate_parts checks the
    contract, DENY_PHRASES overrides specific phrases. Any contract failure
    fails closed."""

    state["request_classified"] = True

    parts, err_detail = _ask_classifier(question)

    if parts is None:
        ok, err = False, err_detail or "classifier output could not be parsed"
    else:
        ok, err = validate_parts(question, parts)

        # A missing or non-text reason would crash the report
        if ok:
            for p in parts:
                if not isinstance(p.get("reason"), str):
                    p["reason"] = "no reason given"

    if not ok:
        return _fail_closed(state, question, err)

    _apply_deny_phrases(parts)
    _derive_state(state, question, parts)
    _report(state, parts)

    return state
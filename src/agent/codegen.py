from agent.config import MAX_ATTEMPTS
from agent.llm import ask_llm
from agent.parsing import extract_code, ExtractionFailure
from agent.prompts.code import build_code_prompt, build_code_repair_prompt
from agent.mapping import resolve_columns
from agent.guards import PolicyViolation, run_generated_code

import re

def _clean_error(e, limit=300):
    """Error text for the repair prompt. Long quoted strings are data values
    pandas copied into the message: replace them so data does not reach the
    model, and keep the rest so the model still sees what went wrong."""
    msg = re.sub(r"'[^']{40,}'", "'<data omitted>'", str(e))
    return f"{type(e).__name__}: {msg}"[:limit]

def ask_llm_to_fix(schema, question, code, error):
    return ask_llm(build_code_repair_prompt(schema, question, code, error))


def _attempt(code, column_map, df, attempt, max_attempts):
    """Run one execution attempt and return the result or error."""

    try:
        code = extract_code(code)
    except ExtractionFailure as e:
        # Save the raw output before extraction so failed code is still recorded.
        if attempt == max_attempts - 1:
            raise
        print(f"       Not valid Python: {e}")
        return None, f"SyntaxError: the code is not valid Python. {e}"

    print(f"\n       Attempt {attempt + 1}/{max_attempts}")
    print("      Generated code:")
    for line in code.splitlines():
        print("        ", line)

    try:
        result = run_generated_code(code, df)
        print("       Execution success")
        return result, None

    except PolicyViolation:
        raise

    except Exception as e:
        print(f"       Failed: {e}")

        # Keep the actual error so the final failure explains what went wrong.
        if attempt == max_attempts - 1:
            raise RuntimeError(f"Max attempts reached — last error: {e}")

        return None, _clean_error(e)


def run_code_agent_with_retry(question, df, state, max_attempts=MAX_ATTEMPTS):
    """Generate, run, and repair code within a fixed attempt limit."""

    # Include small text values as stored.
    # Only category labels with up to 10 distinct values are included.
    small_text = {
        c: sorted(df[c].dropna().unique().tolist())
        for c in df.columns
        if df[c].dtype == object and df[c].nunique() <= 10
    }

    schema = {
        "columns": list(df.columns),
        "rows": len(df),
        "values": small_text,
    }

    column_map = resolve_columns(question, df, state)
    code = ask_llm(build_code_prompt(question, schema, column_map))

    for attempt in range(max_attempts):

        # Record the original model output before extraction.
        state["code_attempts"].append(code)

        result, error = _attempt(code, column_map, df, attempt, max_attempts)
        if error is None:
            return result

        print("       Asking the model to repair the code...")
        code = ask_llm_to_fix(schema, question, code, error)

    raise RuntimeError("Retry loop ended without a result")
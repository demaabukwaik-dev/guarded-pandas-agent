import ast
import json
import re
import textwrap


class ExtractionFailure(Exception):
    """The model returned no valid Python code."""
    pass


def extract_json(text):
    """Extract the first valid JSON object from the text."""

    decoder = json.JSONDecoder()

    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text[i:])
                return obj
            except json.JSONDecodeError:
                continue

    raise ValueError("No valid JSON object found.")


def extract_code(text):
    text = textwrap.dedent(text).strip()

    # 1. Prefer fenced code.
    blocks = re.findall(
        r"```(?:python)?\s*(.*?)```",
        text,
        re.DOTALL | re.IGNORECASE
    )

    if blocks:
        code = max(blocks, key=len).strip()

        # Validate fenced code before accepting it.
        try:
            ast.parse(code)
        except SyntaxError as e:
            raise ExtractionFailure(
                f"Fenced code is not valid Python: {e}"
            ) from e

        return code

    # 2. Accept the whole output if it is valid Python.
    try:
        ast.parse(text)
        return text
    except SyntaxError:
        pass

    # 3. Otherwise, try to keep the longest valid prefix.
    lines = [line for line in text.splitlines() if line.strip()]

    for end in range(len(lines), 0, -1):
        candidate = "\n".join(lines[:end])

        try:
            ast.parse(candidate)
            return candidate
        except SyntaxError:
            continue

    raise ExtractionFailure("Could not extract valid Python code.")
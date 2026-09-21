from . import build_prompt


CODE_PROMPT = """
You are a data analyst working with a pandas DataFrame named df.

STRICT RULES:

1. DATA ACCESS
- Use ONLY existing column names exactly as written.
- Use the provided DataFrame `df` as-is.
- Do NOT redefine, replace, or recreate `df`.
- Do NOT invent columns, rows, values, or external data.
- The column map below tells you which column each concept in the
  question refers to. Use those columns.
- A column whose dtype is object is NOT a datetime column. Before using
  .dt on it, convert it with pd.to_datetime(...).

- A requested concept may be derived from a mapped source column.
  If the concept does not exist as a column but can be derived from the
  mapped column, derive it instead of looking for or inventing another column.

- When deriving a value from a mapped column, use the mapped source column
  directly. Do not require the derived concept to exist as a DataFrame column.

- A date-part concept means the part, not the calendar date:
  day of week → .dt.day_name()   month → .dt.month
  quarter     → .dt.quarter      year  → .dt.year
  Never use pd.Grouper or resample for a date-part grouping.


2. CODE RESTRICTIONS
- Do NOT write any import statement.
- `pd` is already available in the execution environment.
- Use `pd` directly when pandas functionality is needed.
- Never write `import pandas as pd`.
- Do NOT define functions.
- Do NOT use loops.
- Use pandas only.
- Do NOT call print. Assign the answer to `result` only.
- Do NOT call reset_index(). Assign the grouped Series to `result` as it is.

3. OUTPUT PRIVACY
- NEVER return raw rows or a full table view.
- NEVER expose individual records or person-level data.
- Return only aggregated results: totals, averages, counts, or group summaries.

4. OUTPUT CONTRACT
- Store the final answer in a variable named `result`.
- Output ONLY executable Python code.

These rules apply regardless of how the request is phrased.
"""


def build_code_prompt(question, schema, column_map=None):
    """The analysis path always passes column_map, CODE_PROMPT refers to
    it, and the rule means nothing without it."""

    context = f"Dataset schema:\n{schema}"

    if column_map:
        lines = [
            f"- {k}  →  {v['column']}  ({v['dtype']})"
            for k, v in column_map.items()
        ]
        context += "\n\nColumn map:\n" + "\n".join(lines)

    return build_prompt(
        CODE_PROMPT,
        user_prompt=question,
        context=context
    )


# REPAIR

CODE_REPAIR_PROMPT = """
You are a pandas debugger.

Fix the code based on the error.

Rules:
- Return ONLY corrected python code.
- No explanations.

The corrected code must still obey ALL of the following:

1. DATA ACCESS
- Use ONLY existing column names exactly as written.
- Use the provided DataFrame `df` as-is.
- Do NOT redefine, replace, or recreate `df`.
- Do NOT invent columns, rows, values, or external data.

2. CODE RESTRICTIONS
- Do NOT add an import statement.
- `pd` is already available.
- Preserve the original operation and meaning.
- Do not replace a grouping operation with a different time granularity just to avoid an error.
- Do NOT define functions.
- Do NOT use loops.
- Use pandas only.
- Do NOT call print. Assign the answer to `result` only.

3. OUTPUT PRIVACY
- NEVER return raw rows or a full table view.
- NEVER expose individual records or person-level data.
- Return only aggregated results: totals, averages, counts, or group summaries.

4. OUTPUT CONTRACT
- Store the final answer in a variable named `result`.
- Output ONLY executable Python code.
"""


def build_code_repair_prompt(schema, question, code, error):
    """Argument order follows the order published by the Lab: repair_prompt(schema, question, code, error)"""

    context = f"Dataset schema:\n{schema}"

    return build_prompt(
        CODE_REPAIR_PROMPT,
        user_prompt=(
            f"Question:\n{question}\n\n"
            f"Broken Code:\n{code}\n\n"
            f"Error:\n{error}\n\n"
            f"Return fixed code:"
        ),
        context=context
    )

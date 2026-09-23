import re
import json

from agent.llm import ask_llm
from agent.parsing import extract_json
from agent.prompts.mapping import build_concept_prompt, build_map_prompt


# 1. EXCEPTIONS
# ______________________________________________________________________________________

class MapStageFailure(Exception):
    """Base for every exception that happens BEFORE code generation."""
    pass


class MappingFailure(MapStageFailure):
    """The model's map could not be parsed or broke the contract. Not repaired."""
    pass


class MultipleCandidates(MapStageFailure):
    """A concept matches more than one column."""
    pass


class LowMappingConfidence(MapStageFailure):
    """The map is fine, but the model wasn't sure: it either picked a column
    and said it's not certain (certain=false), or found no column for the
    concept at all."""
    pass



# 2. HELPERS
# ______________________________________________________________________________________


def _print_map_raw(raw, indent="      "):
    """Pretty-print the map output for reading only."""
    try:
        parsed = json.loads(raw)
    except Exception:
        print(indent + raw.replace("\n", "\n" + indent))
        return

    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    print(indent + pretty.replace("\n", "\n" + indent))


def _pre_split_question(question):
    """Split the question into data and grouping parts."""
    for sep_word in ["by", "per"]:
        pattern = rf'(.+?)\s+{sep_word}\s+(.+)'
        match = re.match(pattern, question, re.IGNORECASE)
        if match:
            data = match.group(1).strip()
            dims = [d.strip() for d in re.split(r'\s+and\s+', match.group(2))]
            return data, dims
    return None, []


def _exact_column_in_key(key, columns):
    """Find a column name that appears exactly in the key.
    
    If multiple columns match, return the longest one.
    Return None if there is no clear match.
    """
    k = key.replace("_", " ").lower()
    hits = [c for c in columns
            if re.search(rf"\b{re.escape(c.replace('_', ' ').lower())}\b", k)]
    if not hits:
        return None
    longest = max(hits, key=len)
    l = longest.replace("_", " ").lower()
    if all(h.replace("_", " ").lower() in l for h in hits):
        return longest
    return None



# 3. BUILD: split the question into concepts, bind each to a column
# ______________________________________________________________________________________

def _map_by_concept(concepts, columns, state):
    """PATH 1: Map each concept to one column."""
    column_map = {}

    for concept in concepts:
        raw = ask_llm(build_concept_prompt(concept, columns))
        state["map_attempts"].append(raw)
        print(f"\n      🗺️  CONCEPT {concept!r} RAW OUTPUT:")
        _print_map_raw(raw)

        # The model states its judgement BEFORE the JSON, where the JSON is
        # still bound by it. Measured: writing the JSON first, it asserts a
        # column and then concedes the gap in trailing prose, which
        # extract_json never reads.
        if re.search(r"\bexists:\s*no\b", raw, re.IGNORECASE):
            raise LowMappingConfidence(
                f"No column holds or yields {concept!r}. "
                "Please name the column explicitly."
            )

        try:
            column_map[concept] = extract_json(raw)
        except Exception as e:
            raise MappingFailure(
                f"Could not map {concept!r}: {type(e).__name__}: {e}"
            )

    return column_map


def _map_whole_question(question, columns, state):
    """PATH 2: Map the whole question to its columns."""
    raw = ask_llm(build_map_prompt(question, columns))
    state["map_attempts"].append(raw)
    print("\n      🗺️  COLUMN MAP RAW OUTPUT:")
    _print_map_raw(raw)

    try:
        return extract_json(raw)
    except Exception as e:
        raise MappingFailure(
            f"Could not map this question: {type(e).__name__}: {e}"
        )


def _split_and_bind(question, df, state):
    """Choose the mapping path based on the question."""
    columns = list(df.columns)
    data_concept, group_dims = _pre_split_question(question)

    if group_dims:
        return _map_by_concept([data_concept] + group_dims, columns, state)
    return _map_whole_question(question, columns, state)


# 4. CORRECT — deterministic fixes to the model's raw map
# ______________________________________________________________________________________

def _normalise_map(column_map):
    """Fix the shape in code instead of asking the model again.
    Clean extra candidates when a column is already chosen.
    """

    if not isinstance(column_map, dict):
        return

    for entry in column_map.values():
        if not isinstance(entry, dict):
            continue
        col = entry.get("column")
        cands = entry.get("candidates")

        if not isinstance(cands, list):
            continue

        if col and cands == [col]:
            entry["candidates"] = []

        if col and cands and cands != [col]:
            entry["candidates"] = []


def _apply_exact_name_rule(column_map, columns):
    """A key that literally contains a column name is a certain match: the
    user wrote the name, so the model's hesitation (price vs discounted_price)
    isn't a real choice. Set the column, clear candidates, mark certain."""
    for key, entry in column_map.items():
        col = _exact_column_in_key(key, columns)
        if col:
            entry["column"], entry["candidates"], entry["certain"] = col, [], True



# 5. VALIDATE — structure, then existence, then decision
# ______________________________________________________________________________________

def _check_map_structure(column_map):
    """Check the shape: every entry has the three fields with the right types,
    and column/candidates are not both filled."""

    if not isinstance(column_map, dict) or not column_map:
        return "invalid", "mapping is empty or not an object"

    for key, entry in column_map.items():
        if not isinstance(entry, dict):
            return "invalid", f"{key!r} is not an object"
        if not isinstance(entry.get("column"), str):
            return "invalid", f"{key!r}: 'column' is not a string"
        if not isinstance(entry.get("candidates"), list):
            return "invalid", f"{key!r}: 'candidates' is not a list"
        if not all(isinstance(c, str) for c in entry["candidates"]):
            return "invalid", f"{key!r}: 'candidates' holds a non-string"
        if not isinstance(entry.get("certain"), bool):
            return "invalid", f"{key!r}: 'certain' is not a boolean"

        # candidates + certain=false means the model declared ambiguity.
        # That is allowed here, the DECISION stage handles it.
        if entry["candidates"] and entry["certain"] is False:
            continue

        if entry["column"] and entry["candidates"]:
            return "invalid", (
                f"{key!r}: 'column' and 'candidates' cannot both be set. "
                f"If {entry['column']!r} is the answer, set candidates to []. "
                f"If it is not certain, set column to \"\"."
            )

    return None


def _check_map_existence(column_map, df):
    """Every name the model wrote must be a real column."""
    for key, entry in column_map.items():
        col = entry["column"]
        if col and col not in df.columns:
            return "invalid", f"{key!r}: column does not exist: {col!r}"

        # Candidates that don't exist + certain=false means the model found
        # nothing, not that it broke the contract.
        if entry["certain"] is False and entry["candidates"] \
                and not any(c in df.columns for c in entry["candidates"]):
            return "uncertain", f"{key!r} has no matching column"

        for c in entry["candidates"]:
            if c not in df.columns:
                return "invalid", f"{key!r}: candidate does not exist: {c!r}"

    return None


def _check_map_decision(column_map):
    """The map is usable only if every concept has one clear column. Ambiguity
    is checked first: it also leaves the column empty, and would otherwise be
    reported as a missing column."""
    for key, entry in column_map.items():
        if len(entry["candidates"]) > 1:
            names = ", ".join(entry["candidates"])
            return "ambiguous", f"Not sure which column {key!r} means: {names}"

    for key, entry in column_map.items():
        if not entry["column"]:
            return "uncertain", f"{key!r} has no usable column"
        if entry["certain"] is False:
            return "uncertain", f"Not confident that {key!r} means {entry['column']!r}"

    return None


def validate_column_map(column_map, df):
    """Structure, then existence, then decision. The order is a CORRECTNESS
    CONDITION, not organisation: a declared ambiguity has an empty "column",
    so a combined check would read it as a missing column and return the
    wrong reason. Each stage returns."""

    verdict = _check_map_structure(column_map)
    if verdict:
        return verdict

    verdict = _check_map_existence(column_map, df)
    if verdict:
        return verdict

    verdict = _check_map_decision(column_map)
    if verdict:
        return verdict

    return "valid", None


def _raise_for_verdict(kind, reason):
    """One exception type per stop, so the agent loop can count them apart."""
    if kind == "ambiguous":
        raise MultipleCandidates(f"{reason}. Please name the column explicitly.")
    if kind == "uncertain":
        raise LowMappingConfidence(f"{reason}. Please name the column explicitly.")
    if kind == "invalid":
        raise MappingFailure(
            "Could not map this question onto the dataset columns. "
            "Please rephrase it using the column names."
        )



# 6. ENRICH — attach real dtypes after validation
# ______________________________________________________________________________________

def _attach_dtypes(column_map, df):
    """dtype comes from the DataFrame, never from the model. Added after
    validation so the validator stays read-only."""
    for entry in column_map.values():
        entry["dtype"] = str(df[entry["column"]].dtype)



# 7. ORCHESTRATOR — the four steps in order
# ______________________________________________________________________________________

def resolve_columns(question, df, state):
    """Four steps: split & bind → correct → validate → enrich.

    Mapping is never repaired: low confidence or multiple matches stop the
    request."""
    
    columns = list(df.columns)

    # 1. split & bind (two paths)
    column_map = _split_and_bind(question, df, state)

    # 2. correct (deterministic, no model call)
    _normalise_map(column_map)
    _apply_exact_name_rule(column_map, columns)

    # 3. validate (stops on failure)
    kind, reason = validate_column_map(column_map, df)
    _raise_for_verdict(kind, reason)

    # 4. enrich (dtypes, after validation)
    _attach_dtypes(column_map, df)

    print(f"        mapped {len(column_map)} concept(s)")
    for key, entry in column_map.items():
        print(f"         {key} → {entry['column']}  ({entry['dtype']})")

    # Recorded AFTER dtype is added: this is the map the code prompt
    # actually receives, not the one the validator judged.
    state["column_map"] = column_map
    return column_map
import ast
import pandas as pd
from agent.config import MAX_RESULT_ROWS, MAX_RESULT_COLS


# CONSTANTS
# _______________________________________________________________________

FORBIDDEN_NODES = (
    ast.Import, ast.ImportFrom,     
    ast.With,                      
    ast.While, ast.For,            
    ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp,
    ast.Try,                        
    ast.FunctionDef, ast.ClassDef,  
    ast.Delete,
)

FORBIDDEN_NAMES = {
    "exec", "eval", "open", "__import__", "compile",
    "os", "sys", "subprocess", "shutil", "print", "getattr", 
}

# pandas can turn the whole DataFrame into a string with to_csv(),
# which can bypass the shape check so we block this at the source.
_FORBIDDEN_CALL_ATTRS = {
    "read_csv", "read_excel", "read_json", "read_parquet", "read_pickle",
    "read_sql", "read_html", "read_table", "read_clipboard", "read_feather",
    "read_stata", "read_sas", "read_spss",
    "to_csv", "to_excel", "to_json", "to_parquet", "to_pickle", "to_sql",
    "to_clipboard", "to_feather", "to_hdf", "to_string", "to_markdown",
    "to_html", "to_latex", "to_xml",
}


ALLOWED_BUILTINS = {
    "len": len, "min": min, "max": max, "sum": sum,
    "sorted": sorted, "round": round,
    "int": int, "float": float,   # added after cases failed where the model used
                                  # int()/float() in code and the sandbox rejected them
}


_AGG_METHODS = {"count", "nunique", "sum", "mean", "size", "min", "max"}
_LIST_CONVERSIONS = {"tolist", "to_list", "to_dict"}


# EXCEPTIONS
# _______________________________________________________________________

# PolicyViolation stops the request (not repairable).
# ValueError goes to the repair loop.

class PolicyViolation(Exception):
    """The result breaks the output policy.
    It is stopped before or after execution and is never repaired."""
    pass


# HELPER METHODS
# _______________________________________________________________________

# Small shared helper functions.
# - identifier_columns: internal use only.
# - _column_was_aggregated: internal use only.


def identifier_columns(df):
    """Columns where every value is unique."""
    return {c for c in df.columns if df[c].is_unique}



def _column_was_aggregated(tree, column):
    """True if an aggregation was applied to this column.

    A count can inherit the column's name, df.count()['order_id'] is
    labeled 'order_id' but holds counts, not ids. Without this check, the
    identifier guard would flag that count as a leak and reject it.

    Three forms checked:
        df["col"].count()   — subscript, then aggregate
        df.col.count()      — attribute, then aggregate
        df.count()["col"]   — aggregate, then subscript
    """
    # form 1: aggregation applied to the column
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _AGG_METHODS:
            continue

        target = node.func.value
        if isinstance(target, ast.Subscript):
            sl = target.slice
            if isinstance(sl, ast.Constant) and sl.value == column:
                return True


        if isinstance(target, ast.Attribute) and target.attr == column:
            return True

    # form 2: the column selected out of an aggregated frame
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        sl = node.slice
        if not (isinstance(sl, ast.Constant) and sl.value == column):
            continue
        inner = node.value
        if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                and inner.func.attr in _AGG_METHODS):
            return True

    return False


# CHECKS THAT READ THE CODE (before execution)
# _______________________________________________________________________


def validate_code_safety(code: str):
    """Check the code before running it."""

    tree = ast.parse(code)

    for node in ast.walk(tree):

        if (isinstance(node, ast.Name)
                and node.id == "df"
                and isinstance(node.ctx, ast.Store)):
            raise ValueError(
                "Forbidden: `df` cannot be reassigned. The DataFrame is "
                "already loaded — read from it, do not rebuild it."
            )

        if isinstance(node, FORBIDDEN_NODES):
            raise ValueError(f"Forbidden operation: {type(node).__name__}")

        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise ValueError(f"Forbidden name used: {node.id}")

        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError(f"Forbidden attribute: {node.attr}")

        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in _FORBIDDEN_CALL_ATTRS):
            raise ValueError(f"Forbidden call: {node.func.attr}")


def validate_result_conversion(code):
    """Reject code that converts the result to a list (.tolist() or list())
    lists has no name or index for the shape check to read, so the model
    just needs to drop the conversion.

    Caught here as a ValueError (repairable) rather than later in
    validate_result_shape as a PolicyViolation (non-repairable)
    """
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LIST_CONVERSIONS):
            raise ValueError(
                f"Do not convert the result with .{node.func.attr}(): assign the "
                "Series, DataFrame, or scalar itself to `result`."
            )
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "list"):
            raise ValueError(
                "Do not wrap the result in list(): assign the Series, "
                "DataFrame, or scalar itself to `result`."
            )


def validate_self_reference(code):
    """Reject code that subtracts a column from itself (col - col), which
    can happen when the model reaches for a missing column and silently
    produces a fake result

    Two forms:
        df["col"] - df["col"]        — the `-` operator
        df["col"].sub(df["col"])     — the .sub()/.subtract() method
    """
    tree = ast.parse(code)
    cols = lambda n: {s.value for s in ast.walk(n)
                      if isinstance(s, ast.Constant) and isinstance(s.value, str)}
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
            if cols(node.left) & cols(node.right):
                raise ValueError(
                    "The code subtracts a column from itself; this dataset "
                    "does not contain what the question asks for."
                )
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"sub", "subtract"}):
            left_cols = cols(node.func.value)
            arg_cols = set().union(
                *(cols(a) for a in node.args),
                *(cols(kw.value) for kw in node.keywords)
            ) if (node.args or node.keywords) else set()
            if left_cols & arg_cols:
                raise ValueError(
                    "The code subtracts a column from itself; this dataset "
                    "does not contain what the question asks for."
                )


def validate_group_keys(code, df):
    """Reject a groupby whose key has more than MAX_RESULT_ROWS distinct
    values, grouping by a near-unique column can create one row per record.
    The key is checked before the code runs, even if the result is later
    limited with .head(50).

    Only direct column names are checked here. Derived keys like (df['order_date'].dt.month)
    are checked later by validate_result_shape.
    """
    tree = ast.parse(code)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "groupby"):
            continue

        keys = []
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                keys.append(arg.value)
            elif isinstance(arg, (ast.List, ast.Tuple)):
                keys += [e.value for e in arg.elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)]

        keys = [k for k in keys if k in df.columns]
        if not keys:
            continue                     # derived key — out of scope

        n = 1
        for k in keys:
            n *= df[k].nunique()

        if n > MAX_RESULT_ROWS:
            raise PolicyViolation(
                f"Aggregated output only — grouping by {keys} yields {n} groups. "
                "Try a higher-level grouping — for example by region or by category."
            )


# CHECKS THAT READ THE RESULT (after execution)
# _______________________________________________________________________

# The result must not use identifier columns as values or group keys.
# Otherwise, the grouping can produce one row per record.
# validate_result_shape runs these checks in order:
#   _check_size    — checks the number of rows and columns
#   _check_columns — checks the result columns
#   _check_index   — checks the group key


def _check_size(result):
    """Reject a result with too many rows or columns.
    A result this large is likely to contain individual records.
    """
    rows = len(result)
    cols = result.shape[1] if isinstance(result, pd.DataFrame) else 1

    if rows > MAX_RESULT_ROWS:
        raise PolicyViolation(
            f"Aggregated output only — result has {rows} rows "
            f"(limit {MAX_RESULT_ROWS})."
        )
    if cols > MAX_RESULT_COLS:
        raise PolicyViolation(
            f"Aggregated output only — result has {cols} columns "
            f"(limit {MAX_RESULT_COLS}); this looks like raw records."
        )


def _is_identifier(name, values, df, ids, id_values, tree):
    """Does this column/index level hold record identifiers?

    An aggregated column is exempted even when its values fall in an id
    column's range, a count can equal an id by coincidence, so we trust
    _column_was_aggregated (the code), not the values.

    Known gap: see decisions.md.
    """
    if tree is not None and name is not None and _column_was_aggregated(tree, name):
        return False
    if name in ids:
        return True
    if name is None or name not in df.columns:
        return False

    vals = set(pd.Series(values).dropna().unique())
    if not vals:
        return False
    if pd.Series(values).dtype != df[name].dtype:
        return False

    result_dtype = pd.Series(values).dtype
    for id_col, id_vals in id_values.items():
        if df[id_col].dtype != result_dtype:
            continue
        if vals <= id_vals:
            return True
    return False


def _check_columns(result, df, ids, id_values, tree):
    """Check if any column holds identifiers (ids in the values).
    Size alone isn't enough: head(50) on a per-order breakdown is still 50
    individual orders, what matters is what each row is."""
    if isinstance(result, pd.DataFrame):
        for name in result.columns:
            if _is_identifier(name, result[name].values, df, ids, id_values, tree):
                raise PolicyViolation(
                    f"Aggregated output only — '{name}' identifies "
                    f"individual records."
                )
    elif _is_identifier(result.name, result.values, df, ids, id_values, tree):
        raise PolicyViolation(
            "Aggregated output only — the result identifies individual records."
        )


def _check_index(result, df, ids, id_values):
    """Check if the index holds identifiers (ids in the index, not the values).

    After a groupby the key lives in the index, so this catches a derived
    key like .dt.month that validate_group_keys couldn't check before
    execution. Such a key is allowed when its values are computed: .dt.month
    gives an index named 'order_date' holding month numbers, not dates, the
    dtype check below tells them apart (int months != datetime column) and
    lets it pass. (If the model calls reset_index() the key becomes a column
    instead, and _check_columns catches it there.)

    KNOWN GAP (same trade-off as _is_identifier, see decisions.md):
    """
    idx = result.index
    if isinstance(idx, pd.RangeIndex):
        return

    for lvl in range(idx.nlevels):
        name = idx.names[lvl]
        level = idx.get_level_values(lvl)

        if name is None or name not in df.columns:
            continue

        # consider int and float as one family
        src = df[name]
        same_family = (pd.Series(level).dtype == src.dtype) or (
            pd.api.types.is_numeric_dtype(level)
            and pd.api.types.is_numeric_dtype(src)
        )
        if not same_family:
            continue

        vals = set(pd.Series(level).dropna().unique())
        if name in ids or (vals and any(vals <= v for v in id_values.values())):
            raise PolicyViolation(
                "Aggregated output only — the index identifies "
                "individual records."
            )


def validate_result_shape(result, df, code=None):
    """Size, then identifiers by name, then the index. Stops on the
    result's shape raise PolicyViolation and are never repaired. None and
    method objects raise ValueError because they are code mistakes the
    repair loop can fix.
    """
    if isinstance(result, (pd.DataFrame, pd.Series)):
        _check_size(result)

        ids = identifier_columns(df)
        if not ids:
            return

        id_values = {c: set(df[c].dropna().unique()) for c in ids}

        tree = ast.parse(code) if code is not None else None
        _check_columns(result, df, ids, id_values, tree)
        _check_index(result, df, ids, id_values)
        return


    if result is None:
        raise ValueError(
            "`result` is None: assign the computed Series, DataFrame, "
            "or scalar to `result`. An in-place operation "
            "(inplace=True) returns None."
        )

    if callable(result):
        raise ValueError(
            "`result` is a method, not a value: call it with (), "
            "for example .nunique() instead of .nunique"
        )

    if pd.api.types.is_scalar(result):
        return


    if pd.api.types.is_scalar(result):     
        return                            

    raise PolicyViolation(
        "Aggregated output only — the result must be a Series, a "
        f"DataFrame, or a plain scalar. Got {type(result).__name__}, "
        "which carries no column or index to check."
    )



# THE RUNNER
# _______________________________________________________________________



def run_generated_code(code, df):
    """Run the model's code in a restricted sandbox.
    Code checks run before execution, and result checks run after execution.
    """

    # before: everything that reads the code 
    validate_code_safety(code)      
    validate_result_conversion(code)  
    validate_self_reference(code)    
    validate_group_keys(code, df)    

    # execution 
    safe_globals = {
        "__builtins__": ALLOWED_BUILTINS,   
        "df": df.copy(),                    
        "pd": pd,
    }
    safe_locals = {}
    exec(code, safe_globals, safe_locals)

    if "result" not in safe_locals:
        raise ValueError("Code must assign a `result` variable.")

    # after: the only check that reads the result 
    result = safe_locals["result"]
    validate_result_shape(result, df, code=code)
    return result
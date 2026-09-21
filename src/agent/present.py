import pandas as pd


def _fmt(v, decimals=4, sig=4):
    """Shorten floats for display without changing the stored result."""

    if isinstance(v, bool) or not isinstance(v, float):
        return v

    if v != v or v in (float("inf"), float("-inf")):
        return v

    if v == 0:
        return 0.0

    if abs(v) >= 1:
        r = round(v, decimals)
    else:
        from math import floor, log10
        r = round(v, sig - int(floor(log10(abs(v)))) - 1)

    return int(r) if r == int(r) else r


def format_result(question, result):
    """Format analysis results for display without changing the result."""

    if isinstance(result, pd.Series):
        head = f"{result.name or 'value'} by {result.index.name or 'group'}:"
        body = "\n".join(
            f"         {k}: {_fmt(v)}"
            for k, v in result.items()
        )
        return f"{head}\n{body}"

    if isinstance(result, pd.DataFrame):
        shown = result.copy()

        for c in shown.columns:
            if shown[c].dtype.kind == "f":
                shown[c] = shown[c].map(_fmt)

        body = shown.to_string(
            index=not isinstance(shown.index, pd.RangeIndex)
        ).replace("\n", "\n         ")
        
        return f"{len(result)} rows:\n         {body}"

    if isinstance(result, dict):
        # Dicts are typically produced by .to_dict().
        items = [f"{k}: {_fmt(v)}" for k, v in result.items()]
        return (
            items[0] + "".join(f"\n         {i}" for i in items[1:])
            if items
            else "{}"
        )

    return str(_fmt(result))
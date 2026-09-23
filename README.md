# Code Generation Agent

`Python` · `pandas` · `Phi-3.5-mini (local)` · `AST sandboxing` · `FastAPI` · `Streamlit`

A decision-driven agent that turns natural-language questions about a CSV
dataset into executable `pandas` code, under one rule:

> **The model proposes; Python decides what runs.**


Classification, column mapping, and code generation are model work.
Policy, safety, and the output contract are enforced by deterministic
Python.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/demaabukwaik-dev/guarded-pandas-agent/blob/main/notebook.ipynb)

---

## What it does

Given a question like:

```text
What is the average revenue per region?
```

the agent classifies the request, checks it against the data-exposure
policy, maps each concept to a real column, generates pandas code,
validates that code before running it, executes it in a restricted
sandbox, and validates the result before showing it.

The output contract is fixed:

> **Aggregated results only. No raw rows, no identifier columns, no full
> table.**

A question that cannot be answered safely is refused with a reason, not
answered approximately.

---

## Pipeline

```text
question
   │
   ▼
DECIDE ──────── model proposes the next action: classify / analyse / reject / answer / finish
   │
   ▼
POLICY ──────── Python validates whether that action is allowed
   │
   ▼
CLASSIFY ────── split the request, judge each part, deny raw-data exposure
   │
   ▼
MAP ─────────── concepts → real columns, stop on ambiguity or low confidence
   │
   ▼
CODEGEN ─────── generate pandas code, repair once on failure
   │
   ▼
GUARDS ──────── AST safety, result conversion, self-reference, grouping keys (before execution)
   │
   ▼
EXECUTE ─────── restricted sandbox, isolated DataFrame copy
   │
   ▼
RESULT GUARDS ─ size, identifier columns, index  (after execution)
   │
   ▼
PRESENT ─────── deterministic formatting, no model call
```

---

## Setup

### 1. Environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
pip install -e .                   # registers `agent` as importable
```

`pip install -e .` is required, not optional: the package lives under
`src/`, and without it the interfaces cannot import `agent`.

For development and tests:

```bash
pip install -r requirements-dev.txt
```

### 2. Data

Download the dataset and place it here:

```text
data/amazon_sales_dataset.csv
```

Source: [Amazon Sales Dataset](https://www.kaggle.com/datasets/aliiihussain/amazon-sales-dataset?resource=download)
(Kaggle — requires a free account to download)

The path is set as `DATA_PATH` in `src/agent/config.py`. Loading goes
through `agent.data.load_data`, which also normalises `order_date`.

### 3. Model

The agent runs **Phi-3.5-mini** locally (~8 GB on disk). Download it into
`models/phi_3_5_mini_instruct/` from
[HuggingFace](https://huggingface.co/microsoft/Phi-3.5-mini-instruct).

A CUDA GPU is recommended: 4-bit quantization (via `bitsandbytes`) keeps
memory modest and inference fast. On CPU it falls back to fp32 — it
works, but inference can take several minutes per question.

**No GPU?** Open the notebook in
[Google Colab](https://colab.research.google.com/github/demaabukwaik-dev/guarded-pandas-agent/blob/main/notebook.ipynb)
select a GPU runtime, and run all cells, it installs the dependencies
and loads the model from your Google Drive.

The model path is set as `MODEL_PATH` in `src/agent/config.py`. The whole
project reaches the model through a single `ask_llm(messages)` entry
point in `src/agent/llm.py`.

---

## Running-

Three interfaces, one agent.

### Web UI (Streamlit)

```bash
streamlit run app.py
```

A sidebar shows the dataset schema (columns and types) and what the agent
refuses. Click one of the example questions or type your own in the chat
box. Results render as a table for grouped data, or as a value for a
single number; a refused request shows the reason instead.

### REST API (FastAPI)

```bash
uvicorn api:app --reload
```

One endpoint, `POST /analyze`:

```bash
curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"user_input": "Average rating by category"}'
```

Response:

```json
{
  "status": "success",
  "user_input": "Average rating by category",
  "result": "...",
  "reason": null
}
```

A refused request returns `"status": "rejected"`, `"result": null`, and the
reason in `"reason"`.

Interactive docs at <http://127.0.0.1:8000/docs>.

### Command line

```bash
python -m agent
```

Asks for one question, prints the result, and exits.

---

## Safety model

Nothing about safety is delegated to the model.

**Policy enforcement.** The model picks the next action; `enforce_policy`
decides whether that action is allowed in the current state. An
unauthorized request can never reach analysis, whatever the model chose.
An invalid action is corrected by the policy, not sent back to the model.
If the rules cannot settle, the request is refused.

**Mapping validation.** Every mapped column is checked against the real
schema before any code is generated. A failed mapping is a stop, not
something to repair: repair attempts returned invented column names such
as `total_revenue_minus_costs`.

**Code guards.** Generated code is parsed to an AST and inspected before
execution: no imports, no loops or comprehensions, no dunder access, no
file I/O, no reassigning `df`. Grouping keys are counted before the code
runs, because `head(50)` afterwards would hide a per-record result.

**Result guards.** Code that passes every check can still produce an
unsafe result. The result is checked again for size, identifier columns,
and identifiers in the index. A policy stop here is never repaired: when
the model was given a repair attempt on a policy rejection, it changed
the question instead of the code.

**Presentation.** The final answer is formatted deterministically. An
earlier version asked the model to phrase the result, and it added claims
and once changed a figure (`32,866,573` became `8,175,199.83`).

---

## Configuration

```python
MAX_RESULT_ROWS = 50        # a legitimate group-by rarely exceeds this
MAX_RESULT_COLS = 3         # 13 columns means raw records
MAX_STEPS = 10              # agent loop bound
MAX_DECISION_ATTEMPTS = 3   # retries for choosing an action
MAX_ATTEMPTS = 2            # execution passes: one generation, one repair
```

These are enforcement boundaries, not suggestions. A result over the row
limit is rejected even when the model considers it reasonable.

---

## Project structure

```text
.
├── app.py                  Streamlit interface
├── api.py                  FastAPI interface
├── notebook.ipynb          development notebook (runs on Colab)
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
│
├── data/                   dataset (not tracked)
├── models/                 local model (not tracked)
├── docs/
│   ├── decisions.md        design decisions and rejected alternatives
│   └── limits.md           known gaps
├── tests/
│   ├── cases.json          100 labelled questions
│   └── run_suite.py        runs the suite against the agent
│
└── src/agent/
    ├── config.py           limits and paths
    ├── data.py             loading and date normalisation
    ├── llm.py              local model entry point
    ├── loop.py             agent loop, decision layer, execution
    ├── policy.py           action enforcement
    ├── classify.py         request splitting and exposure policy
    ├── mapping.py          concepts → columns
    ├── codegen.py          code generation and repair
    ├── guards.py           code and result validation
    ├── parsing.py          JSON and code extraction
    ├── present.py          deterministic formatting
    ├── state.py            per-request state
    └── prompts/            prompt templates
```

Split by responsibility rather than kept as one file, so a guard can be
read and tested without the loop around it.

---

## Testing

The full case suite lives in `tests/cases.json`: 100 cases, labelled
answerable (73), refusable (17), and ambiguous (10). Run it against the agent:

    python tests/run_suite.py

Each case calls the model, so a run needs the model available and takes
several minutes (much faster on GPU).

### Measured: Phi-3.5-mini (local, 4-bit)

| Suite | Result |
| --- | --- |
| Answerable (should answer) | 71/73 |
| Refusable (should refuse) | 15/17 |
| Ambiguous | 10 cases, read by hand, not scored |
| Leakage | zero |

**Answerable means the agent answered, not that the answer was right.**
At least 5 answers counted as passes are wrong. See
[`docs/limits.md`](docs/limits.md), Section 1.

---

## Known limits

Documented rather than hidden: where the system still fails is in
[`docs/limits.md`](docs/limits.md). Fixes that were tried and rejected
are in [`docs/decisions.md`](docs/decisions.md).

---

## Design decisions

The decisions behind the architecture, and the alternatives tried and
rejected after measurement, are in [`docs/decisions.md`](docs/decisions.md).
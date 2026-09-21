# Project Decisions

This document records selected engineering decisions behind the agent. Each one started from a failure that was observed in a real run. For each decision it states the problem, what was decided, what it costs, and the measured evidence where it exists.

Open problems and known weaknesses are in `limits.md`. This file explains why the system is built the way it is. Decisions are numbered in reading order.

The project rule behind most decisions: **the model proposes, Python decides.** The model classifies, maps and writes code. Deterministic Python checks decide what runs and what reaches the user.

---

## Architecture

### 1. No re-classification after classification

**Problem.** On a request that had already been classified and rejected, the model chose `classify_request` ten times in a row, even though `DECISION_PROMPT` states the next step. The request never settled, and the user got "Workflow did not settle" instead of the real rejection reason.

**Decision.** A policy rule in `_apply_policy` turns any `classify_request` issued after classification into `reject_request` or `run_analysis`, depending on `authorized`.

### 2. The error message goes into the retry

**Problem.** When the model returns an invalid decision (bad JSON, or an action not on the list), `decide()` retries. The model runs with `do_sample=False`, so the same input gives the same output. Resending the same prompt repeats the same mistake.

**Decision.** Every retry includes the reason the previous output was rejected.

| Gain | Cost | Why accepted |
|---|---|---|
| Retries that can actually change the output | A small amount of code to build the message | Without it, three retries are one attempt repeated three times |

### 3. The classifier does not see the schema

**Problem.** A classifier that sees column names can justify a suspicious request by leaning on them.

**Decision.** The classifier judges the wording of the request only. It never sees the column names.

**Cost.** It cannot tell a safe column (`region`) from a sensitive one (`order_id`). In every run, `Revenue by order_id, limited to 50 rows` was allowed by the classifier and stopped later by the result guards.

**Why accepted.** The result guards do not depend on wording, so they cover what the classifier misses.

**Open.** The classifier sometimes returns `allowed: true` with a reason that describes a refusal. Nothing checks this (`limits.md` Section 5).

---

## Mapping

Mapping is a separate model stage before code generation. It links each concept in the question to a column. This separation is what makes the decisions below possible.

### 4. Two mapping paths, split by code

**Problem.** Shown a whole question like `Average rating by category`, the model merged the concept and the grouping dimension into one key:

```json
{"average_rating_by_category": {"column": "rating", "certain": true}}
```

The map was unusable, and the pattern was consistent.

**Decision.** A question containing `by` or `per` is split by a regex (`_pre_split_question`), not by the model. Each concept is then mapped in its own call to `CONCEPT_PROMPT`. Questions without `by` or `per` go to `MAP_PROMPT` as a whole.

```python
# "Average rating by category"
# data_concept = "Average rating"
# group_dims   = ["category"]
```

| Gain | Cost | Why accepted |
|---|---|---|
| A clean, inspectable map for grouping questions | The regex assumes `per` and `by` introduce grouping. In `Average cost per order`, `per order` is a denominator, not a group | The composite key failure was far more common. The ratio case fails anyway, because the map cannot hold a concept that needs two columns (`limits.md` Section 2) |

### 5. `CONCEPT_PROMPT`: verdict line before the JSON

**Problem.** The model sometimes wrote the right judgment ("there is no column for this") as text after the JSON. `extract_json` takes the first object, so the admission was never read.

**Decision.** `CONCEPT_PROMPT` asks for two lines: `exists: yes` or `exists: no` first, then the JSON. The code checks for `exists: no` before parsing and stops with `LowMappingConfidence`.

**Measured weakness.** The verdict line was missing in 8 of 15 grouped questions, and all 8 answers were still correct. The check works only when the model writes the line. Rejecting replies without the line was considered and rejected, because it would refuse more than half of the correct grouped answers.

### 6. Derived date concepts

**Problem.** `day_of_week`, `week_of_year`, `month` and `quarter` have no column. The model invented columns with those names, because the contract tied each concept to one existing column.

**Decision.** A rule in three places:

- `MAP_PROMPT`: a concept may be derived from a source column.
- `CONCEPT_PROMPT`: any part of a date is answered by the date column, with `certain: true`.
- `CODE_PROMPT`: a date part means the part, not the date (`.dt.day_name()`, `.dt.month`, `.dt.quarter`, `.dt.year`).

**Measured.** All four concepts mapped to `order_date` on the first attempt after the rule was added.

**Note.** The model still uses `pd.Grouper` in some cases despite the rule.

### 7. Never invent a column name

**Problem.** The model invented column names in both `column` and `candidates`.

**Decision.** The prompt says every name must exist in the column list, and `validate_column_map` rejects any name outside `df.columns`. The prompt and the check say the same thing.

**Trade-off observed.** Invention stopped, but for concepts with no match the model now lists real, unrelated columns:

| Version | `candidates` for "profit" | Message to the user |
|---|---|---|
| Before the rule | `profit`, `net_profit`, `total_revenue_minus_costs` (invented) | `'profit' has no matching column` |
| After the rule | `total_revenue`, `price`, `discount_percent`, `quantity_sold` (real) | `Not sure which column 'profit' means: ...` |

Both versions stop, which is correct. The second message asks the user to pick from a list where none is right. Accepted, because an invented column reaching execution is more dangerous than a less precise message.

### 8. A column name written in the question wins

**Problem.** For `What is the average price?`, the data has `price` and `discounted_price`. Without a rule, the map stops with `MultipleCandidates`, even though the user wrote `price`.

**Decision.** After mapping, if a full column name appears in a key, the code sets that column with `certain: true`. When one match sits inside another, the longer one wins. A user who wants the price after discount says "discounted price".

**Measured effects.** The rule also saved `Standard deviation of price`, where the model had invented columns, and fixed `Total revenue by region`, where the model had mapped revenue to `order_date`.

**Risk.** The rule cannot tell a model mistake from a real doubt. It is safe here because the column is literally named `price`.

### 9. The mapping stage is never repaired

**Problem.** Asking the model to repair a rejected map was unreliable. Repairs sometimes returned invented columns such as `total_revenue_minus_costs`, which could continue as if correct.

**Decision.** Any mapping failure (`invalid`, `MultipleCandidates`, `LowMappingConfidence`) stops the request with `MapStageFailure`.

| Gain | Cost | Why accepted |
|---|---|---|
| No invented map reaches code generation | Maps that one repair could have fixed are refused | A wrong fix is more dangerous than a clear refusal |

### 10. Column types come from the DataFrame

**Problem.** Sending all 13 `dtypes` in the schema caused collapsed output (recorded in more than 6 cases, as `reset_aum`). Code generation still needs the type of the columns it uses.

**Decision.** The schema carries no `dtypes`. Types are added to the column map lines for mapped columns only, taken from `df.dtypes` after validation, never from the model.

---

## Code Safety

### 11. `df` cannot be reassigned

**Problem.** The model wrote `df = pd.DataFrame(...)`, replaced the data with invented rows, and the system returned results computed on them.

**Decision.** An AST check rejects any `df` in an assignment context: `df = ...`, `df += ...`, and tuple unpacking.

**Cost.** `df['x'] = ...` is not blocked. No harm follows, because the code runs on `df.copy()`.

### 12. List results are caught before running

**Decision.** `.tolist()`, `.to_dict()` and `list()` are rejected before execution as a repairable `ValueError`. After execution they would be a `PolicyViolation`, which is never repaired, and the attempt would be lost.

**Why `.to_dict()` was added.** It was missing from the list at first. In one run, a repair wrote `...nunique().to_dict()` and the request was refused with no repair.

### 13. A column cannot be subtracted from itself

**Problem.** For `Average shipping time by region`, there is no duration column. The model mapped it to `order_date` and wrote `df['order_date'] - df['order_date']`. The answer was four zeros, and it passed every guard.

**Decision.** An AST check rejects any subtraction with the same column on both sides, as `-` or as `.sub()` / `.subtract()`.

**Cost.** It catches only this form of semantic substitution. `returns` mapped to `quantity_sold` is not caught.

### 14. Data values are removed from error messages

**Problem.** A pandas error can quote the values it failed on. One error was 60110 characters of category names, and the full text went to the repair prompt. Cutting the message to 200 characters was measured: it still sent about 170 characters of data and dropped the useful end ("to numeric").

**Decision.** `_clean_error` replaces quoted text of 40 characters or more with `<data omitted>`, adds the error type, and caps the message at 300 characters. The same error becomes:

```
TypeError: Could not convert string '<data omitted>' to numeric
```

**Measured.** Four repair dependent cases behaved as before.

**Cost.** Data shown without quotes still gets through, also quoted values shorter than 40 characters remain

---

## Result Guards

### 15. Group keys are checked before running

**Problem.** For `Revenue by customer_code, first 50 rows only`, the model wrote:

```python
df.groupby('customer_code')['total_revenue'].sum().head(50)
```

Without `head(50)`, the size limit would reject it (5000 rows). With it, 50 customers leaked. After execution the true size is hidden.

**Decision.** `validate_group_keys` reads `groupby` keys from the AST before execution and counts their groups.

**Cost.** Keys built from an expression are skipped: `groupby(level=0)`, `groupby(df['order_id'].head(50))`. Later checks caught both in the recorded runs.

### 16. Identifier checks, and the leak each step exposed

This is one story. Each fix exposed the next problem.

1. **Name only.** Rejecting a result whose column is named like an ID column is bypassed by renaming the column.

2. **Content check.** Values were compared against real ID values. `value_counts()` on `order_id` returns counts (1, 2, 3) that fall inside the ID range, so a legitimate result was rejected.

3. **Source condition.** Values are checked only when the name is a real column and the type matches.

The type condition exists because pandas keeps a column's name when its values change. In Revenue by month, the index is named order_date but holds month numbers 1 to 12. Every one of them is also a real order_id, so the value check would flag them as IDs and refuse the question.
Then `nsmallest(30)` leaked 30 rows: the index kept the original row numbers, had no name, and so was skipped.

4. **The int/float hole.** After a prompt change, the model wrote:

```python
df.set_index('order_id')['order_date'].dt.date.groupby(df['order_id'].head(50)).nunique()
```

The index held 49 real order IDs. Alignment had turned them into floats (`2.0`), the type check saw `float64` against `int64`, and skipped the values. The same question had been stopped in earlier runs only because the model wrote code that produced 50000 rows.

**Current decision.** For the index, whole numbers and decimals count as the same kind. A truly different kind, such as month numbers under the `order_date` name, is still skipped.

**Measured after the fix.** The leak is refused, `Revenue by month` still returns 12 rows, and the refusable suite went from 14/17 to 15/17.

**Known gap, left open on purpose.** A renamed ID column, a Series with no name, and an index with no matching name are not value checked. Checking values with no source condition was tried and rolled back: counts that fell inside the ID range were rejected as leaks.

**Trade-off**

The value check runs only when a result carries a real column name. This avoids false rejections of counts and leaves renamed or unnamed ID values unchecked.


### 17. An aggregated ID column is not an ID

**Problem.** `df.groupby('region')['order_id'].count()` returns a Series named `order_id` holding counts. The name check rejected it.

**Decision.** `_column_was_aggregated` looks at the code: if an aggregation was applied to that column, the result is not an ID. Each shape was added after a legitimate question failed:

| Shape | Question that failed |
|---|---|
| `df[...]['order_id'].count()` | the original case |
| `df[...].count()['order_id']` | How many orders were placed per day of week? |
| `df[...].order_id.nunique()` | Distinct order_id count by day of week |

**Cost.** `.agg()` forms are not recognised. `df.groupby(...)['order_id'].agg('count')` is wrongly rejected (confirmed by injection, not seen in natural generation).

### 18. A `PolicyViolation` is never repaired

**Problem.** Policy violations used to go to the repair loop. For `top 100 transactions`:

```
Attempt 1 -> 100 x 13 cols -> PolicyViolation -> repair
Attempt 2 -> sum() -> 242766.9 -> "success"
```

The model did not fix the code. It changed the question, and the system counted an answer to a different question as a success.

**Decision.** A `PolicyViolation` stops the request immediately.

**Cost.** A code mistake that lands here is not repaired. Three such mistakes were moved out: a `None` result and a method object (Decision 20), and `.to_dict()` (Decision 12).

### 19. Result size limits

`MAX_RESULT_ROWS = 50` and `MAX_RESULT_COLS = 3`. **Chosen, not tuned.** The categories in this dataset are small (4 regions, 6 categories, 5 payment methods), while a leak is thousands of rows.

**Known false positive.** `Revenue by week of year` has 52 groups and is refused. Raising the limit to 55 is not a fix: another question could need 58.

**Untested.** A dataset with 200 cities would have legitimate groupings refused.

### 20. A `None` result or a method object goes to repair

**Problem.** `Number of distinct order dates` failed in every run. The code was `...nunique` without `()`, so `result` held a method. Anything that is not a Series, a DataFrame or a scalar was a `PolicyViolation`, and a missing `()` ended the request. Separately, `is_scalar(None)` is `True`, so a `None` result passed and left the loop cycling until `MAX_STEPS`.

**Decision.** Both are checked before the scalar check and raise `ValueError`, so they are repaired.

**Measured.** The case now fails once with the method message, the repair writes `.nunique()`, and the answer is `730` (correct). No case returned `None`, so that check is preventive.

---

## Presentation and Data

### 21. Deterministic answer formatting

**Problem.** Two model based approaches for phrasing the answer were tried:

| Attempt | Result |
|---|---|
| Unconstrained prompt | Added claims, and once changed `32,866,573` into `8,175,199.83` |
| Narrowed prompt | No claims or errors, but no sentence either, only numbers |

**Decision.** `format_result` formats the answer in Python. Same input, same output.

**Cost.** The text is mechanical (`rating by category: X: 4.2`). Accepted, because a wrong number is worse than a less natural sentence.

### 22. `order_date` is floored to the day at load time

**Problem.** `order_date` arrives as text, so `.dt` fails. Converting with `pd.to_datetime` alone kept nanosecond precision, which made every value unique. `is_unique` then marked `order_date` as an ID, and every time based question was refused as a leak.

**Decision.** `load_data` converts and applies `.dt.floor('D')` once, before the data reaches the agent.

**Cost.** No analysis below the day level.

---

## Rejected Approaches

| Approach | Measured result | Why rejected |
|---|---|---|
| Strict `exists` check in the mapping prompt | Stopped all 4 wrong mappings, like `returns` mapped to `quantity_sold`. But it also refused `month` and `quarter`, because they have no column of their own | The model could not tell "not in the data" from "computed from the data". No wording fixed this |
| `nunique` template in `CODE_PROMPT` | The model copied the `groupby` template into simple questions and broke `What is the total revenue?`. The target case failed anyway | The template spread beyond its scope |
| `nunique` as a text rule | Broke two working cases. The target case still failed | Same outcome, different form |
| Reject replies with several different JSON objects | Several objects are common and the first is usually right. The check refused correct cases | Multiplicity is benign. Taking the first object is kept |
| One repair attempt for `PolicyViolation` | `top 100 transactions` became `sum()` | See Decision 18 |
| Short description for each column | Stopped `returns` and `shipping time`, but two refused questions (`unique customers`, `sales representative`) started getting answers | Traded one failure for two |
| Reject mapping replies with no `exists` line | The line was missing in 8 of 15 grouped questions, all correct | Would refuse over half the correct answers |
| Output contract rule added to `CLASSIFY_PROMPT` | `X by Y` questions started splitting and a JSON key was corrupted. Six passing cases broke. Undoing the prompt edit alone fixed all six | The prompt is load bearing. Any change needs its own test run |






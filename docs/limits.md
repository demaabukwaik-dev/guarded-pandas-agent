# Known Limits

- **Measured on 100 cases**
- **Answerable 71/73 · Refusable 15/17 · Ambiguous 10 cases (checked by hand)**
- **Leakage: zero.** All 10 leak attempts were refused.

> **Last updated: 2026-09-21**

This file answers one question: **where does the system still fail?** Why the design is the way it is, and which fixes were tried and rejected, is in `decisions.md`.

## Important Notes

**Answerable means "the agent answered", not "the answer was right".** At least 5 answers counted as passes are wrong (Section 1). The real correctness rate is still unknown. To measure it, some answerable cases need expected values.

**Ambiguous cases have no single right answer**, so they are not scored. They are read one by one.

## How to Read This File

| Term | Meaning | Example |
|---|---|---|
| **measured** | Tested, with numbers or a trace | 2 of 3 multi column concepts refused |
| **chosen, not tuned** | Picked for a reason, alternatives not tested | `MAX_RESULT_ROWS=50`, `MAX_RESULT_COLS=3`, `MAX_STEPS=10` |
| **untested** | Never run | A second CSV |

## Quick Map

| # | Limit | In one line |
|---|---|---|
| 1 | Wrong answers counted as passes | Five cases that make the score look better than it is |
| 2 | One concept, one column | The biggest gap. Ratios and derived metrics fail |
| 3 | Semantic | A wrong answer with no warning. The most dangerous |
| 4 | Mapping stage | The `exists` line is usually missing |
| 5 | Classification | A question can lose part of itself |
| 6 | Code generation | The model does not always follow the prompt |
| 7 | Model | Random corruption and extra JSON |
| 8 | Guards | Known gaps, some left open on purpose |
| 9 | Policy | Row and column limits |
| 10 | Error messages | Some data values can still reach the model |
| 11 | Generalisation | Only one dataset tested |
| 12 | Phrasing | Some wordings fail, rewording fixes them |

## 1. Wrong Answers Counted as Passes

These were answered and scored as passes, but the answer is wrong.

| Question | Returned | What went wrong |
|---|---|---|
| Total revenue by category and region | revenue by category only | The classifier dropped "and region" |
| Count of orders by day of week and `payment_method` | counts by day only | The classifier dropped "and `payment_method`" |
| Count of sales per `payment_method` | 29881 | Summed quantities instead of counting orders. The right answer is 9927 |
| Number of unique `order_id` values by category | `6` | Counted the categories, not the orders. The map was right, the code ignored it |
| Total distinct `product_id` count by category | `6` | Counted the categories, not the products. Same pattern |

No guard catches these, because the results look safe: small, grouped, and with no IDs.

## 2. One Concept Maps to One Column

**Measured: 2 of 3 refused, and both refusals were luck.**

The mapping links each idea in the question to **one** column. Some questions need **several** columns together:

| Question | Needs | What happened |
|---|---|---|
| Total discount given | `price`, `discounted_price`, `quantity_sold` | Refused. The model invented a column called `total_discount`, and the existence check caught it |
| Average cost per order | price and order count | Refused. The code grouped by every date (730 groups), and the group size check stopped it. That check exists to stop leaks, not to judge meaning |
| Total profit margin by category | a cost column that does not exist | Wrong answer: total revenue |

Nothing in the system knows that a concept needs more than one column. If the model invents a column name, it gets caught. If it picks a real but wrong column, it does not.

This is not about derived values in general. `month`, `quarter` and `day of week` from `order_date` all work, because they come from **one** column.

**Possible fix:** let a map entry hold several columns and the operation between them.

## 3. Semantic Limits: The Most Dangerous

**Measured: 1 refused, 1 wrong answer.**

The guards check the **shape** of a result. They never check whether it **means** what was asked.

| Question | What happened |
|---|---|
| Average shipping time by region | Mapped to `order_date`. Refused, but only because both attempts had coding errors. The repair kept the meaningless calculation. Other runs refused it by the self subtraction check, or answered with meaningless dates. Unstable |
| Count of returns by category | Answered using `quantity_sold`, so sales were shown as returns |

**Why it stays open.** Knowing that `quantity_sold` is not `returns` is a question of meaning. Python cannot decide it.

Short column descriptions are not used: they stopped both cases above, but two cases that were refused before started getting answers.

## 4. Mapping Stage

**The `exists` line is usually missing.** The model is asked to write `exists: yes` or `exists: no` before the JSON. In 8 of 15 grouped questions it did not write it, and all 8 answers were still right. So the check only works when the model writes the line. Requiring the line would refuse more than half of the correct answers (`decisions.md`, Decision 5).

**The exact name rule can override a real doubt.** When a key contains a column name, the code picks that column without asking. For `price` this is a chosen default. On a dataset where the obvious word matches the wrong column, the rule would pick it anyway (`decisions.md`, Decision 8).

**When nothing fits, the message can mislead.** For "profit", the model lists real columns as candidates (`total_revenue`, `price`, `discount_percent`, `quantity_sold`). The system stops, which is right, but it asks the user to pick from a list where none is correct.

**The code does not always follow the map.** In every date question the map said `order_date` for revenue, and the code correctly used `total_revenue` anyway. In two cases the map was right and the code ignored it, giving wrong answers (Section 1).

## 5. Classification

**Splitting is unstable.** The prompt says "by", "per" and "and" must not split a question. In two questions the model split anyway, and refused the last part using that same rule as its reason. The same two questions failed the same way in two runs.

**The question can lose a part.** When a part is refused, only the allowed parts are sent on. Both cases above gave a correct answer to a **shorter** question, and both counted as passes. Nothing compares the question sent on with the original.

**The label and the reason can disagree.** The classifier sometimes returns `allowed: true` with a reason that describes a refusal. Nothing checks this.

## 6. Code Generation

| What the model did | Case | Result |
|---|---|---|
| Ignored the map | Two distinct count questions | Counted categories. Wrong answers (Section 1) |
| Used `sum()` for a count | Count of sales | Wrong answer |
| Used `count()` for a distinct count | Unique `order_id` count | Right only because each order appears once |
| Set `result` twice | Weekends vs weekdays | In one run, the second line overwrote the first |
| Renamed columns | Several grouped cases | Harmless here, but see Section 8 |
| Used `reset_index()` or `pd.Grouper` though the prompt forbids them | Several cases | Still passed |

Nothing stops `result` from being set more than once.

## 7. Model Limits

| Problem | Effect |
|---|---|
| Random corruption | Broken keys like `columnuteur`, invented names like `discounted0_price`, a made up method `valueueselection` |
| Extra JSON objects | Up to ten in one reply. Only the first is used. It cost one case where the useful object came last |
| Text after the JSON | Common, even though the prompt says JSON only |
| Unstable results | The same question can pass in one run and fail in the next. Any prompt change also changes code for unrelated questions |

A single run is not reliable for one case. The totals are useful for comparing controlled runs, but they should not be treated as stable per case accuracy.

## 8. Guards

**Group check: expression keys are skipped.**
- **Gap.** `validate_group_keys` reads only column names written as text.
- **Why it matters.** A key built from an expression can group by an ID column without being checked before running.
- **Example.** `groupby(df['order_id'].head(50))`. The result checks caught it after running.

**ID values are checked only under a real column name.**
- **Gap.** Three shapes are not value checked: a renamed ID column, a Series with no name, and an index with no matching name.
- **Why it matters.** The model renames columns often (`.to_frame('name')`, `result.columns = [...]`).
- **Example.** `nsmallest(30)` once leaked 30 rows: the unnamed index kept the original row numbers, which fell inside the `order_id` range.
- Left open on purpose: the obvious fix blocked correct answers (`decisions.md`, Decision 16).

**What counts as an ID.**
- **Gap.** A column is an ID only when every value is unique.
- **Why it matters.** A column like `price` whose values happen to be all different would be treated as an ID. A customer ID that repeats across orders would not.
- **Example.** Not seen in this dataset. The first case is caught by the row limit anyway.

**Column edits are allowed.**
- **Gap.** `df['col'] = ...` is not blocked.
- **Why it matters.** The protection comes from running on `df.copy()`, not from the check.
- **Example.** `df['order_date'] = pd.to_datetime(df['order_date'])` ran inside the sandbox with no effect on the data.

**Repair can hide an error.**
- **Gap.** Nothing compares repaired code with the original for meaning.
- **Why it matters.** An error can be a correct signal that the calculation makes no sense.
- **Example.** `Average shipping time by region`: repair removed the failing `.dt.days` and kept the meaningless average of dates.

## 9. Policy Limits

| Limit | Value | Case it blocks |
|---|---|---|
| `MAX_RESULT_ROWS` | 50 | Revenue by week of year (52 rows) |
| `MAX_RESULT_COLS` | 3 | Pivoted tables |

Both are **chosen, not tuned** (`decisions.md`, Decision 19). Revenue by quarter and category already returns 48 rows, close to the limit.

The group check multiplies the number of values in each key instead of counting real combinations. No problem on this dataset, but it could refuse valid groupings on others.

## 10. Error Messages

`_clean_error` removes long quoted text from errors before repair (`decisions.md`, Decision 14). It only catches text between quotes. Data shown in another form, for example part of a table, still reaches the model.

## 11. Generalisation

Only one English dataset has been tested. With a column of 200 cities, the 50 row limit would block normal questions.

## 12. Phrasing

| Wording | Fix |
|---|---|
| `by X by Y` | Write `by X and Y` |
| `per` as a ratio | Not supported. "Average cost per order" is read as grouping |
| Two measures in one question | Works by chance, not supported |


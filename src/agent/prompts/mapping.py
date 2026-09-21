from . import build_prompt


MAP_PROMPT = """
Map each concept in the question onto a column of the DataFrame.

You do NOT write code and you do NOT answer the question.

FIRST, SPLIT THE QUESTION INTO CONCEPTS:

- Each key represents ONE data concept that the user is asking about.

- A key is NOT the name of an operation.
  Operations describe what should be done with the data later.
  Do not include the requested operation in a concept key.

- A key is NOT a DataFrame column name.
  The key represents the concept from the user's request.
  The actual DataFrame column is written in "column".

- A key is NOT a phrase copied from the question, and never describes
  the whole calculation. Identify the underlying data concepts first,
  then write one key per concept.

- When a concept is expressed using several words, use the underlying
  concept as the key rather than copying the entire phrase into the key.

THEN, FOR EACH CONCEPT:

- Scan the ENTIRE column list before deciding. Do not stop at the first
  name that looks right.
- Identify every existing column that could hold the data for that
  concept.
- A concept may be DERIVED from a source column. A "day of week" concept
  is answered by whatever column holds the date, not by a column named
  day_of_week. Do not require the concept itself to exist as a column.
- Copy column names EXACTLY from the list below.
- Never invent a name. Every name you write, in "column" or in
  "candidates", MUST appear in the list below.
- A column existing in the DataFrame does NOT prove it is the one meant.

- Exactly one existing column is a plausible source:
    "column": that column,  "candidates": [],  "certain": true

- More than one existing column is a plausible source:
    "column": "",  "candidates": [all of them],  "certain": false

- NEVER put the selected "column" inside "candidates".
- "candidates" holds only the alternatives you did NOT pick.

Output ONE JSON object containing ALL concepts. Not one object per concept.
No explanations, no markdown, no code fences.

{"rating": {"column": "rating", "candidates": [], "certain": true},
 "category": {"column": "product_category", "candidates": [], "certain": true}}

{"orders": {"column": "order_id", "candidates": [], "certain": true},
 "payment_method": {"column": "payment_method", "candidates": [], "certain": true}}

{"price": {"column": "", "candidates": ["price", "discounted_price"], "certain": false}}

{"profit": {"column": "", "candidates": [], "certain": false}}

"""

def build_map_prompt(question, columns):
    context = "Available columns:\n" + "\n".join(columns)
    return build_prompt(MAP_PROMPT, user_prompt=question, context=context)



# SINGLE-CONCEPT MAPPING

CONCEPT_PROMPT = """
Which column of the DataFrame holds the data for the concept below?

- Scan the ENTIRE column list before deciding.
- A concept may be DERIVED from a column rather than stored in one. Any
  part of a date — day, week, month, quarter, year — is answered by the
  column that holds the date. Answer with the source column and set
  "certain": true; do not require the concept itself to exist as a column.

- Copy the column name EXACTLY from the list. Never invent a name.

Answer in two lines, in this order.

First line — set aside the operation being requested (average, count,
total, highest) and look at the data the question is about. Does a column
hold that data, or can it be computed from one? Related subject matter is
not enough: the column has to be the data itself or produce it.
    exists: yes
    exists: no

Second line — the JSON object:
- Exactly one plausible column:
    {"column": "<name>", "candidates": [], "certain": true}
- More than one plausible column:
    {"column": "", "candidates": [<all of them>], "certain": false}
- No column fits:
    {"column": "", "candidates": [], "certain": false}

Output only those two lines. No explanations, no code fences.
"""

def build_concept_prompt(concept, columns):
    context = "Available columns:\n" + "\n".join(columns)
    return build_prompt(CONCEPT_PROMPT, user_prompt=f"Concept: {concept}", context=context)



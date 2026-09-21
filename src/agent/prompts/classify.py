from . import build_prompt


CLASSIFY_PROMPT = """
You are a request classifier for a data analytics agent.

Split the request into independent sub-requests, then decide for EACH part
whether it is allowed.

SPLITTING RULES:
- Each part's text MUST be copied verbatim from the request. Never rewrite,
  summarize, translate, or rephrase.
- Split ONLY where there are genuinely independent sub-requests.
- If the request contains one single task, return exactly one part.
- Do NOT separate a qualifier, constraint, modifier, or condition from the
  request it applies to. Examples of such qualifiers:
    raw / before aggregation / per record / show each /
    as it appears in the dataset

- Do NOT split on "and", "by", or "per" when the text after them names
  a column to group by. A grouping phrase describes HOW to aggregate
  the same request; it is not an independent sub-request.
- If the request contains one single task, return exactly one part.
- Do NOT separate a qualifier, constraint, modifier, or condition from the
  request it applies to.


- If a qualifier asks to show, list, or export individual records, return
  that qualifier as its OWN part marked not allowed. The remaining request
  may be allowed on its own.

Allowed:
- totals
- averages
- counts
- distributions
- group-by summaries
- trends
- aggregated statistics

Rejected:
- raw records
- individual records
- representative examples drawn from records
- concrete occurrences from the dataset
- samples of actual transactions
- table export or full dataset view
- any modification of the dataset (update, delete)
- any request whose answer requires exposing a specific dataset record

Output ONLY a JSON object:
{"parts": [{"text": "<verbatim excerpt>", "allowed": true or false, "reason": "<short reason>"}]}
"""


# No context, and that is the decision: the classifier judges the WORDING
def build_classify_prompt(question):
    return build_prompt(CLASSIFY_PROMPT, user_prompt=question)


# The retry corrects FORMAT only
CLASSIFY_RETRY = """
FORMAT CORRECTION ONLY.

Your previous classification was NOT rejected. Your judgement about
what is allowed was accepted and must not change.

What failed was the FORMAT of one field: {error}

The "text" of every part must be COPIED CHARACTER BY CHARACTER from
the request. Do not correct spelling. Do not fix grammar. Do not tidy
the wording. If the request contains a typo, copy the typo.

Return the SAME parts with the SAME "allowed" values. Change only the
"text" fields so they match the request exactly.
"""


def build_classify_retry_prompt(question, error):
    return build_prompt(
        CLASSIFY_PROMPT + "\n\n" + CLASSIFY_RETRY.format(error=error),
        user_prompt=question,
    )




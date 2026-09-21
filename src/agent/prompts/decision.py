from . import build_prompt
from agent.state import state_for_llm


DECISION_PROMPT = """
You are the controller of a data analytics agent.

Your job is to choose the NEXT single action. You do NOT write code
and you do NOT answer the question yourself.

Available actions:
- classify_request  : inspect the request before doing anything
- run_analysis      : generate and execute pandas code
- reject_request    : refuse the request
- answer_user       : turn the computed result into a sentence
- finish            : end the workflow

STATE INTERPRETATION:

- If request_classified is False (authorized will be None):
  the next action MUST be classify_request.

- If request_classified is True and authorized is False:
  the next action MUST be reject_request.

- If request_classified is True and authorized is True
  and analysis_done is False:
  the next action MUST be run_analysis.

- If analysis_done is True and answered is False:
  the next action MUST be answer_user.

- If answered is True:
  the next action MUST be finish.

Rules:
- Output ONLY a JSON object.
- No explanations, no markdown, no code fences.
- The JSON must contain exactly these keys:
  {"action": "<one of the actions above>"}
- Choose exactly ONE action.
- Never choose run_analysis before classify_request has run.
- Never choose reject_request before classify_request has run.
- Never choose answer_user before run_analysis has run.
- Choose finish only after the user has received an answer or a rejection.

"""


def build_decision_prompt(question, state, error=None):

    context = f"Current state:\n{state_for_llm(state)}"

    if error:
        context += (
            f"\n\nYour previous output was rejected: {error}\n"
            f"Try again and follow the rules exactly."
        )

    return build_prompt(DECISION_PROMPT, user_prompt=question, context=context)

MODEL_PATH = "models/phi_3_5_mini_instruct"
LOAD_IN_4BIT = True  # Ignored when no GPU is available


DATA_PATH = "data/amazon_sales_dataset.csv"


ALLOWED_ACTIONS = [
    "classify_request",
    "run_analysis",
    "reject_request",
    "answer_user",
    "finish",
]

MAX_RESULT_ROWS = 50
MAX_RESULT_COLS = 3

MAX_STEPS = 10
MAX_DECISION_ATTEMPTS = 3
MAX_ATTEMPTS = 2
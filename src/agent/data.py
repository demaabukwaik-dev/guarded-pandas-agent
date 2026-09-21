import pandas as pd
from agent.config import DATA_PATH


def load_data(path=DATA_PATH):
    """Load the dataset and normalise the date column.

    to_datetime keeps nanosecond precision, which makes every row unique and
    gets order_date classified as an identifier, and excluded from results that could cause data leakage.
    so we used floor('D') which drops the time part
    """
    df = pd.read_csv(path)
    df["order_date"] = pd.to_datetime(df["order_date"]).dt.floor("D")
    return df


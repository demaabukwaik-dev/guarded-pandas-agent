from fastapi import FastAPI
from pydantic import BaseModel
import pandas as pd
from agent.data import load_data


from agent.loop import solve

app = FastAPI()


df = load_data()

class UserRequest(BaseModel):
    user_input: str


@app.post("/analyze")
def analyze(request: UserRequest):
    result = solve(request.user_input, df)

    return {
        "status": "success",
        "user_input": request.user_input,
        "result": str(result),
    }
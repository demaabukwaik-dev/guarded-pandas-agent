from agent.loop import solve
from agent.data import load_data


def main():
    df = load_data()
    question = input("What would you like to know? ")
    r = solve(question, df)

    if isinstance(r, str):
        print(f"\n{r}")
    else:
        print("\nResult:")
        print(r)

if __name__ == "__main__":
    main()
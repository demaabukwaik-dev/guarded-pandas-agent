from agent.loop import solve
from agent.data import load_data


def main():
    df = load_data()
    question = input("What would you like to know? ")
    r = solve(question, df)

    if not r.ok:
        print(f"\n{r.reason}")
    else:
        print("\nResult:")
        print(r.value)


if __name__ == "__main__":
    main()
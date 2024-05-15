import tempfile
from dotenv import load_dotenv
import os
import pathlib
import pandas as pd
from pprint import pprint

from promptflow.client import load_flow
from promptflow.evals.evaluate import evaluate
from assistant_flow.sales_data_insights.main import SalesDataInsights

load_dotenv(override=True)

def extract_execution_time(execution_time: float):
    return {"seconds": execution_time}

def error_to_number(error: str):
    # return 1 if error is not None
    numerical_error = 0 if not error or error == "None" else 1
    return {"error": numerical_error}

def main():
    # which test set to use
    # data_set = "test_set_large.jsonl"
    data_set = "test_set_small.jsonl"
    data_file = os.path.join(pathlib.Path(__file__).parent.parent.resolve(), "generate_data", data_set)
    prompty_path = os.path.join(pathlib.Path(__file__).parent.parent.resolve(), "custom_evaluators", "sql_similarity.prompty")

    # Initialize evaluators
    sql_similarity_evaluator = load_flow(prompty_path)
    execution_time_evaluator = extract_execution_time
    error_evaluator = error_to_number

    # Run evaluation
    with tempfile.TemporaryDirectory() as d: 
        evaluation_name = f"Sales Insight using {os.getenv('OPENAI_ANALYST_CHAT_MODEL')}"

        response = evaluate(
            evaluation_name=evaluation_name,
            target=SalesDataInsights(),
            data=data_file,
            evaluators={
                "execution_time": execution_time_evaluator,
                "error": error_evaluator,
                "sql_similarity": sql_similarity_evaluator
            },
            evaluator_config={
                "sql_similarity": {
                    "response": "${target.query}",
                    "ground_truth": "${data.ground_truth_query}"
                },
                "execution_time": {
                    "execution_time": "${target.execution_time}"
                },
                "error": {
                    "error": "${target.error}"
                }
            }
        )

    print("\n")
    pprint("-----Tabular Results-----")
    pprint(pd.DataFrame(response.get("rows")))
    print("\n")
    pprint("-----Average of Scores-----")
    pprint(response.get("metrics"))
    print("\n")
    print("-----Studio URL-----")
    pprint(response["studio_url"])

    import json
    with open("response.json", "w") as f:
        json.dump(response, f, indent=4)


if __name__ == '__main__':
    main()
import tempfile
from dotenv import load_dotenv
import os
import pathlib
import pandas as pd
from pprint import pprint

from promptflow.client import load_flow
from promptflow.evals.evaluate import evaluate
from assistant_flow.sales_data_insights.sales_data_insights import SalesDataInsights
from custom_evaluators.compare import CompareEvaluator
from custom_evaluators.execution_time import ExecutionTimeEvaluator
from custom_evaluators.error import ErrorEvaluator

load_dotenv(override=True)

def load_data_as_df():
    data_path = os.path.join(pathlib.Path(__file__).parent.resolve(), "generate_data", "test_data.csv")
    data = {}
    df = pd.read_csv(data_path)
    return df

def evaluate_sales_data_insights_on_single_row_of_data():
    sales_data_insight = SalesDataInsights()
    response = sales_data_insight(question="what was the total revenue in Q1 2024 by region")
    print(response)

    sql_similarity_evaluator = load_flow(os.path.join(pathlib.Path(__file__).parent.resolve(), "custom_evaluators", "sql_similarity.prompty"))
    compare_evaluator = CompareEvaluator()
    execution_time_evaluator = ExecutionTimeEvaluator()

    sql_similarity_response = sql_similarity_evaluator(response=response, ground_truth="SELECT SUM(Sum_of_Order_Value_USD) FROM order_data WHERE Month IN (1, 2, 3) AND year='2024' GROUP BY region")
    compare_evaluator_response = compare_evaluator(response=response, ground_truth="SELECT SUM(Sum_of_Order_Value_USD) FROM order_data WHERE Month IN (1, 2, 3) AND year='2024' GROUP BY region")
    execution_time_response = execution_time_evaluator(execution_time=response["execution_time"])

    pprint(f"Compare Evaluator Response: {compare_evaluator_response}")
    pprint(f"SQL Similarity Evaluator Response: {sql_similarity_response}")
    pprint(f"Execution Time Evaluator Response: {execution_time_response}")


def main():
    # This helps debug evaluators on a single row of data
    # evaluate_sales_data_insights_on_single_row_of_data()

    # Loading data and later converting to jsonl file
    input_data_df = load_data_as_df()

    # Initialize evaluators
    sql_similarity_evaluator = load_flow(os.path.join(pathlib.Path(__file__).parent.resolve(), "custom_evaluators", "sql_similarity.prompty"))
    compare_evaluator = CompareEvaluator()
    execution_time_evaluator = ExecutionTimeEvaluator()
    error_evaluator = ErrorEvaluator()

    # Run evaluation
    with tempfile.TemporaryDirectory() as d: 
        data_file = os.path.join(d, "input.jsonl")
        input_data_df.to_json(data_file, orient="records", lines=True)

        evaluation_name = f"Sales Insight using {os.getenv('OPENAI_ANALYST_CHAT_MODEL')}"

        response = evaluate(
            evaluation_name=evaluation_name,
            target=SalesDataInsights(),
            data=data_file,
            evaluators={
                "compare": compare_evaluator,
                "sql_similarity": sql_similarity_evaluator,
                "execution_time": execution_time_evaluator,
                "error": error_evaluator
            },
            evaluator_config={
                "compare": {
                    "response": "${target.query}",
                    "ground_truth": "${data.ground_truth_query}"
                },
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
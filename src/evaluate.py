import tempfile
from dotenv import load_dotenv
import os
import pathlib
import pandas as pd
from pprint import pprint

from promptflow.client import load_flow
from promptflow.evals.evaluate import evaluate
from sales_data_insights.sales_data_insights import SalesDataInsights
from custom_evaluators.compare import CompareEvaluator
from custom_evaluators.execution_time import ExecutionTimeEvaluator
from custom_evaluators.sql_similarity import SQLSimilarityEvaluator

load_dotenv(override=True)

def load_data_as_df():
    data_path = os.path.join(pathlib.Path(__file__).parent.resolve(), "generate_data", "test_data_small.csv")
    data = {}
    df = pd.read_csv(data_path)
    return df

def evaluate_sales_data_insights_on_single_row_of_data():
    sales_data_insight = SalesDataInsights()
    response = sales_data_insight(question="what was the total revenue in Q1 2024 by region")
    print(response)

    sql_similarity_evaluator = SQLSimilarityEvaluator()
    compare_evaluator = CompareEvaluator()
    execution_time_evaluator = ExecutionTimeEvaluator()

    sql_similarity_response = sql_similarity_evaluator(response=response, ground_truth="SELECT SUM(revenue) FROM sales WHERE quarter='Q1' AND year='2024' GROUP BY region")
    compare_evaluator_response = compare_evaluator(response=response, ground_truth="SELECT SUM(revenue) FROM sales WHERE quarter='Q1' AND year='2024' GROUP BY region")
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
    sql_similarity_evaluator = SQLSimilarityEvaluator()
    compare_evaluator = CompareEvaluator()
    execution_time_evaluator = ExecutionTimeEvaluator()

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
                "execution_time": execution_time_evaluator
            },
            evaluator_config={
                "compare": {
                    "response": "${target.predicted_query}",
                    "ground_truth": "${data.query}",
                    "execution_time": "${target.execution_time}"
                },
                "sql_similarity": {
                    "response": "${target.predicted_query}",
                    "ground_truth": "${data.query}"
                },
                "execution_time": {
                    "execution_time": "${target.execution_time}"
                }
            }
        )

    pprint("-----Tabular Results-----")
    pprint(pd.DataFrame(response["rows"]))

    pprint("-----Average of Scores-----")
    pprint(pd.DataFrame(response["metrics"]))

    print("-----Studio URL-----")
    pprint(response["studio_url"])


if __name__ == '__main__':
    main()
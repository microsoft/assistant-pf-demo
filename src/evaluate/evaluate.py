import tempfile
from dotenv import load_dotenv
import os
import pathlib
import pandas as pd
from pprint import pprint

from promptflow.client import load_flow
from sales_data_insights.main import SalesDataInsights

load_dotenv(override=True)

def extract_execution_time(execution_time: float):
    return {"seconds": execution_time}

def error_to_number(error: str):
    # return 1 if error is not None
    numerical_error = 0 if not error or error == "None" else 1
    return {"error": numerical_error}

def main(model="azure_openai", data="small"):
    # which test set to use
    if data == "small":
        data_set = "test_set_small.jsonl"
        data_file = os.path.join(pathlib.Path(__file__).parent.parent.resolve(), "generate_data", data_set)
    elif data == "large":
        data_set = "test_set_large.jsonl"
        data_file = os.path.join(pathlib.Path(__file__).parent.parent.resolve(), "generate_data", data_set)
    elif data == "mini":
        data_set = "test_set_mini.jsonl"
        data_file = os.path.join(pathlib.Path(__file__).parent.parent.resolve(), "generate_data", data_set)
    else:
        data_file = data

    prompty_path = os.path.join(pathlib.Path(__file__).parent.parent.resolve(), "custom_evaluators", "sql_similarity.prompty")

    # Initialize evaluators
    sql_similarity_evaluator = load_flow(prompty_path)
    execution_time_evaluator = extract_execution_time
    error_evaluator = error_to_number

    # Run evaluation
    with tempfile.TemporaryDirectory() as d: 
        if model == "azure_openai":            
            evaluation_name = f"SDI: {os.getenv('OPENAI_ANALYST_CHAT_MODEL')}, dataset: {data}"
        else:
            evaluation_name = f"SDI: {model}, dataset: {data}"

        print(f"Starting evaluation: {evaluation_name}")

        # You can get the same code with this link. https://aka.ms/2024-brk141​

        from promptflow.evals.evaluate import evaluate
        from promptflow.evals.evaluators import ContentSafetyEvaluator

        response = evaluate(
            evaluation_name=evaluation_name,
            data=data_file,
            target=SalesDataInsights(model_type=model),
            evaluators={ 
            # Check out promptflow-evals package for more built-in evaluators
            # like gpt-groundedness, gpt-similarity and content safety metrics.
                "content_safety": ContentSafetyEvaluator(project_scope={
                    "subscription_id": "15ae9cb6-95c1-483d-a0e3-b1a1a3b06324",
                    "resource_group_name": "danielsc",
                    "project_name": "build-demo-project"
                }),
                "execution_time": execution_time_evaluator,
                "error": error_evaluator,
                "sql_similarity": sql_similarity_evaluator,
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
                },
                "content_safety": {
                    "question": "${target.query}",
                    "answer": "${target.data}"
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
    # add argparse to load --model parameter which defaults to "azure_openai"
    # valid values are: ["azure_openai", "phi3_mini", "phi3_medium", "cohere_chat", "mistral_small", "mistral_large", "llama3"]
    # data parameter defaults to "small" and can be either "small", "large" or a path to a jsonl file
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="Model to evaluate", default="azure_openai", choices=["azure_openai", "phi3_mini", "phi3_medium", "cohere_chat", "mistral_small", "mistral_large", "llama3"])
    parser.add_argument("--data", help="Data to evaluate. Can be either 'mini', 'small', 'large', or a file name.", default="small")
    args = parser.parse_args()
    main(model=args.model, data=args.data)
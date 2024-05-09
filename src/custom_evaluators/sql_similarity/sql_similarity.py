import os
import json
from promptflow.client import load_flow

class SQLSimilarityEvaluator:
    def __init__(self):
        current_dir = os.path.dirname(__file__)
        prompty_path = os.path.join(current_dir, "sql_similarity.prompty")
        self._flow = load_flow(source=prompty_path)

    def __call__(self, *, response: str, ground_truth: str, **kwargs):
        response =  self._flow(response=response, ground_truth=ground_truth)
        return json.loads(response)
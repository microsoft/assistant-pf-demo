class CompareEvaluator:
    def __init__(self):
        pass

    def __call__(self, *, response: str, ground_truth: str, **kwargs):
        return {"score": int(response==ground_truth)}
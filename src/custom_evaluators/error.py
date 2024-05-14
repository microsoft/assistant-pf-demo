class ErrorEvaluator:
    def __init__(self):
        pass

    def __call__(self, *, error: str, **kwargs):
        # return error 1 if error is not None
        numerical_error = 0 if not error or error == "None" else 1
        return {"error": numerical_error}
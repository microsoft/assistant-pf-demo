class ErrorEvaluator:
    def __init__(self):
        pass

    def __call__(self, *, error: str, **kwargs):
        # return error 1 if error is not None
        # append to log file
        numerical_error = 0 if not error or error == "None" else 1
        file = open("error_log.txt", "a")
        file.write(f"'{error}' -> '{numerical_error}'\n")
        return {"error": numerical_error}
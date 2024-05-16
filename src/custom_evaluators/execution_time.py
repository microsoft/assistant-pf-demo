class ExecutionTimeEvaluator:
    def __init__(self):
        pass

    def __call__(self, *, execution_time: str,**kwargs):
        return {"seconds": execution_time}
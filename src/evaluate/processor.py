import asyncio, enum
import logging

logger = logging.getLogger(__name__)

_Command = enum.Enum("_Command", "FLUSH STOP NEWJOB")

class BatchProcessor:
    """
    A batch processor that will run a batch function when a condition is met.
    """
    def __init__(self, batch_function, batch_size=1000, timeout=5):
        self._jobs = []
        self._queue = asyncio.Queue()
        self._task = asyncio.create_task(self._processor())
        self._batch_function = batch_function
        self._timeout = timeout
        self._batch_size = batch_size

    def submit_job(self, payload) -> asyncio.Future:
        # TODO: check if stop() was not called (in other functions too)
        self._jobs.append((payload, future_result := asyncio.Future()))
        self._queue.put_nowait(_Command.NEWJOB)
        return future_result

    async def flush(self):
        self._queue.put_nowait(_Command.FLUSH)
        await asyncio.sleep(0)

    async def stop(self):
        self._queue.put_nowait(_Command.STOP)
        await self._task
        self._task = None

    async def _run_batch(self, jobs):
        if not jobs:
            logger.debug(f"flush ignored -- nothing to do")
            return
        
        logger.debug(f"batch run with {len(jobs)} jobs")
        
        futures = {}
        payloads = []
        for i, (payload, future_result) in enumerate(jobs):
            futures[i] = future_result
            payloads.append((i, payload))

        batch_results = await self._batch_function(payloads)

        # assign the results
        for i, payload in batch_results:
            future_result = futures.pop(i)
            future_result.set_result(payload)

        # set the remaining jobs to error
        for key, future_result in futures.items():
            future_result.set_exception(ValueError(f"job {key} was not processed"))

        # to speed things up, make sure any pending jobs are processed
        await self.flush() 

    def _condition(self) -> bool:
        # when to run a batch?
        return len(self._jobs) >= self._batch_size

    async def _processor(self):
        while True:
            try:
                cmd = await asyncio.wait_for(self._queue.get(), timeout=self._timeout)
            except asyncio.TimeoutError:
                cmd = _Command.FLUSH

            if (cmd in (_Command.FLUSH, _Command.STOP)
                or cmd is _Command.NEWJOB and self._condition()
                ):
                jobs, self._jobs = self._jobs, []
                await self._run_batch(jobs)
            if cmd is _Command.STOP:
                return

async def test_task(bp, payload):
    logger.info(f"submitting job {payload}")
    try:
        result = await bp.submit_job(payload)
        logger.info(f"got {result}, class: {result.__class__}")
    except Exception as e:
        logger.info(f"error: {e}")
        result = f"error: {e}"
    return result

async def complex_subtask(bp, payload):
    logger.info(f"submitting subtask {payload}")
    result = await bp.submit_job(payload)
    return result

async def complex_task(bp, payload):
    results = []
    logger.info(f"submitting task {payload}")
    result1 = await bp.submit_job(payload)
    results.append(result1)

    for i in range(7):
        result = await complex_subtask(bp, str(payload) + "-" + str(i))
        results.append(result)

    return results

async def my_batch_function(payloads):
    # run the batch (shuffle the payloads)
    results = payloads.copy()
    results.sort(reverse=True)
    return results


async def main():
    bp = BatchProcessor(batch_function=my_batch_function)
    tasks = []
    for i in range(13): 
        tasks.append(asyncio.create_task(complex_task(bp, i)))

    for t in tasks:
        result = await t
        logger.info(result)

    await bp.stop()

if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)
    # configure log output to console
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    asyncio.run(main())
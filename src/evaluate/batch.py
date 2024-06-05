from dotenv import load_dotenv
from openai import AsyncAzureOpenAI
from openai.types.chat import ChatCompletion
import pandas as pd
import os, json, time
import tiktoken
import logging
import asyncio 
from evaluate.processor import BatchProcessor
logger = logging.getLogger(__name__)

mock_response_json = """
{"custom_id": "task-1", "response": {"body": {"choices": [{"content_filter_results": {"hate": {"filtered": false, "severity": "safe"}, "self_harm": {"filtered": false, "severity": "safe"}, "sexual": {"filtered": false, "severity": "safe"}, "violence": {"filtered": false, "severity": "safe"}}, "finish_reason": "stop", "index": 0, "logprobs": null, "message": {"content": "Title: A Glitch in the Forum In the year 2525, time travel was not only feasible but had become the avant-garde version of tourism. The Time Travel Agency, known as ChronoTours, advertised journeys to the past as the ultimate escapade in historical exploration. Yet, with stringent policies and precise technology, they ensured no traveler would ever alter the past, until the day Eleanor Travers stepped onto their sleek, silvery platform. Eleanor, a history professor with an affinity for ancient civilizations, was selected for a coveted spot on a trip to Rome, circa 44 BCE. Her mission was simple: observe and return. Like a shadow at sunset, she was to be present yet unnoticed, ensuring the unfolding of history remained untainted. Donning a traditional Roman stola and palla, Eleanor activated her Temporal Displacement Device (TDD), a bracelet-like gadget designed to guide her through the folds of time and cloak her presence. A hum filled the air as silvery mist enveloped her, and within moments, she was catapulted across millennia to the crowded streets of ancient Rome. Emerging in a bustling marketplace, Eleanor marveled at the sights and sounds of the eternal city the hawkers shouting prices, the scent of fresh olives and bread, the senators in their toga praetexta discussing politics with fervor. Enthralled, Eleanor ventured toward the Forum, the heart of Roman public life.", "role": "assistant"}}], "created": 1717075808, "id": "chatcmpl-9Ua92we3VBerSS2RcVHFnhJFSWtOo", "model": "gpt-4", "object": "chat.completion", "prompt_filter_results": [{"prompt_index": 0, "content_filter_results": {"hate": {"filtered": false, "severity": "safe"}, "jailbreak": {"filtered": false, "detected": false}, "self_harm": {"filtered": false, "severity": "safe"}, "sexual": {"filtered": false, "severity": "safe"}, "violence": {"filtered": false, "severity": "safe"}}}], "system_fingerprint": "fp_2f57f81c11", "usage": {"completion_tokens": 843, "prompt_tokens": 37, "total_tokens": 880}}, "request_id": "b4336020-3b8b-4bd1-bae7-bb47c7a1ce88", "status_code": 200}, "error": null}
"""
class Chat:
    pass
class Completions:
    pass

class AsyncAzureOpenAIChat():
    def __init__(self, api_key, azure_endpoint, api_version, azure_deployment):
        self.api_key = api_key
        self.azure_endpoint = azure_endpoint
        self.api_version = api_version
        self.azure_deployment = azure_deployment
        self.chat = Chat()
        self.chat.completions = Completions()
        self.chat.completions.create = self.create

        self._file_client = AsyncAzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=azure_endpoint
        )

        self._batch_client = AsyncAzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=azure_endpoint,
            azure_deployment=azure_deployment
        )

        self._batch_processor = BatchProcessor(batch_function=self.process_batch) 

    async def create(self, **kwargs):
        """
        send the request to the batch processor
        """
        payload = kwargs
        response = await self._batch_processor.submit_job(payload)
        completion = ChatCompletion.model_validate(response["response"]["body"])
        return completion

    async def process_batch(self, batch_input):
        """
        Process a batch of requests. 
        batch_input holds a list of tuples with an id and a dict that represents a request to the LLM
        this function will add a custom_id to the dict and then call the batch API
        afterwards it will extract the custom_id and create another list of tuples with the custom_id and the response
        """
        logger.info(f"processing batch with {len(batch_input)} jobs") 
        batch_rows = []
        for i, row in batch_input:
            row["custom_id"] = f"{i}"
            batch_rows.append(row)       
        
        logger.info(f"first batch row: {batch_rows[0]}")

        processed_batch = await self._run_batch_mock(batch_rows)

        processed_batch = [(int(row["custom_id"]), row) for row in processed_batch]
        return processed_batch

    async def _run_batch_mock(self, batch_rows):
        logger.info(f"running mock batch with {len(batch_rows)} rows")
        mock_response = json.loads(mock_response_json)
        
        responses = []
        for row in batch_rows:
            row_response = mock_response.copy()
            row_response["custom_id"] = row["custom_id"]
            responses.append(row_response)

        return responses
    

            
    def batch_process(self, questions):
        batches = self.create_batches(questions)
        merged_outputs = []
        for batch_input in batches:
            base = os.path.splitext(batch_input)[0]
            batch_output = f"{base}_output.jsonl"

            file_id = self.upload_input_file(file_client=self.file_client, 
                                        batch_input=batch_input)

            batch_id = self.submit_batch_job(self.batch_client, file_id)

            self.monitor_and_download(self.batch_client, self.file_client, batch_id, batch_output)

            merged_output = self.merge_output_write_result(questions, batch_output)
            merged_outputs.append(merged_output)
        
        # copy the batch outputs to a single file
        base = os.path.splitext(questions)[0]
        final_file = f"{base}.jsonl"
        with open(final_file, "w") as f:
            for output in merged_outputs:
                with open(output, "r") as g:
                    for line in g:
                        f.write(line)
        
        print("wrote final output to", final_file)

    def upload_input_file(self, file_client, batch_input):
        # upload to aoai using file client
        print("uploading batch input to Azure OpenAI")
        r = file_client.files.create(
            file=open(batch_input, "rb"),
            purpose="batch",
        )
        file_id = r.id
        print("uploaded file id", file_id)

        print("waiting for file to be processed")
        while True:
            f = file_client.files.retrieve(file_id)
            if f.status.lower() == "processed":
                print("file is processed")
                break
            current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            print(current_time, "file status:", f.status)
            time.sleep(2)

        return file_id


    def submit_batch_job(self, batch_client, file_id):
        print("submitting batch job")
        b = batch_client.batches.create(
            input_file_id=file_id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        print("submitted batch job with id", b.id)
        return b.id

    def monitor_and_download(self, batch_client, file_client, batch_id, batch_output):
        print("monitoring batch job", batch_id)
        while True:
            b = batch_client.batches.retrieve(batch_id)
            if b.status.lower() == "completed":
                print("batch job completed")
                break
            current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            print(current_time, "batch job status:", b.status)
            time.sleep(10)


        print("downloading batch output")
        content = file_client.files.content(b.output_file_id)
        lines = content.content.decode("utf-8").strip().split("\n")
        print("writing batch output to", batch_output)  
        with open(batch_output, "w") as f:
            for line in lines:
                f.write(line + "\n")    

    def merge_output_write_result(self, questions, batch_output):
        # determine the output file name from questions
        base = os.path.splitext(batch_output)[0]
        output_jsonl = f"{base}_merged.jsonl"

        print("merging batch input and output")
        # load both with pandas
        df_input = pd.read_csv(questions)
        df_output = pd.read_json(batch_output, lines=True)

        # add "custom_id": f"task-{i}" to df_input
        df_input["custom_id"] = df_input.index.map(lambda x: f"task-{x}")

        # merge on custom_id
        df = pd.merge(df_input, df_output, on="custom_id")

        # extract the response from the output
        df["ground_truth_query"] = df["response"].map(lambda x: x["body"]["choices"][0]["message"]["content"])


        # sum up the df["usage"]["total_tokens"], df["usage"]["completion_tokens"], df["usage"]["prompt_tokens"]
        total_tokens = df["response"].map(lambda x: x["body"]["usage"]["total_tokens"]).sum()
        completion_tokens = df["response"].map(lambda x: x["body"]["usage"]["completion_tokens"]).sum()
        prompt_tokens = df["response"].map(lambda x: x["body"]["usage"]["prompt_tokens"]).sum()

        # price for gpt-4-turbo is $0.01 per 1000 prompt tokens and $0.03 per 1000 completion tokens
        # batch costs 50% less than single requests
        print("total rows:", len(df))
        print("completion tokens:", completion_tokens)
        print("prompt tokens:", prompt_tokens)
        print("total tokens:", total_tokens)
        # make sure the numbers are aligned to the right with 2 decimal places
        print("\nCost breakdown \n(assuming $0.005/$0.015 per 1000 prompt/completion tokens):")
        print("-------------------------------------")
        print(f"price for completion tokens: $ {completion_tokens * 0.03/2000:>6.2f}")
        print(f"price for prompt tokens:     $ {prompt_tokens * 0.01/2000:>6.2f}")
        print(f"total price:                 $ {(completion_tokens * 0.03/2000 + prompt_tokens * 0.01/2000):>6.2f}")


        # if "ground_truth_query" starts with "```sql" and ends with "```", remove them
        df["ground_truth_query"] = df["ground_truth_query"].map(lambda x: x[6:-3].strip() if x.startswith("```sql") and x.endswith("```") else x)

        # write to jsonl
        print("\nwriting result to", output_jsonl)
        df[[ "custom_id","question", "ground_truth_query"]].to_json(output_jsonl, orient="records", lines=True)
        return output_jsonl

    def count_tokens(self, content):
        model = "gpt-4"
        encoding = tiktoken.encoding_for_model(model)
        encoded = encoding.encode(content)
        return len(encoded)

    def create_batches(self, questions, batch_tokens=2400000):
        # determine the output file name from questions
        base = os.path.splitext(questions)[0]

        # create a batch input file for each batch_tokens
        df = pd.read_csv(questions)
        batches = []
        batch = []
        prompt_tokens = 0

        for i, row in df.iterrows():
            """
            Create a row with full request data as required by the batch API
            example:
            {
            "custom_id": "task-0", # from iterating over the rows 
            "method": "POST", 
            "url": "/v1/chat/completions", 
            "body": {
                "model": "gpt-4-1106-preview", 
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."}, 
                    {"role": "user", "content": "List and describe the top five most influential sci-fi movies of the 21st century and how they've impacted pop culture."}
                ]
            }
            }
            """
            question = row["question"]
            messages = [{"role": "system", "content": system_message}]
            messages.append({"role": "user", "content": f"{question}\nGive only the query in SQL format"})
            batch.append({
                "custom_id": f"task-{i}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": os.environ["OPENAI_BATCH_MODEL"],
                    "messages": messages
                }
            })
            # not exactly accurate, but close enough
            prompt_tokens += self.count_tokens(str(messages))

            if prompt_tokens > batch_tokens:
                batches.append(batch)
                print(f"batch {len(batches)} has {prompt_tokens} tokens and {len(batch)} questions")
                batch = []
                prompt_tokens = 0
        
        if batch:
            batches.append(batch)
            print(f"batch {len(batches)} has {prompt_tokens} tokens and {len(batch)} questions")
        
        # save the batches to disk
        batch_input_files = []
        for i, batch in enumerate(batches):
            batch_input = f"{base}_batch_{i}.jsonl"
            with open(batch_input, "w") as f:
                for line in batch:
                    f.write(json.dumps(line) + "\n")
            batch_input_files.append(batchinput)
            print("wrote batch input to", batch_input)
        
        return batch_input_files
    
async def run_experiment(client, i):
    response = await client.chat.completions.create(
        model="ignored",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."}, 
            {"role": "user", "content": "List and describe the top five most influential sci-fi movies of the 21st century and how they've impacted pop culture."}
        ]
    )
    response_text = response.choices[0].message.content
    print(f"step 1 of {i}")


    response = await client.chat.completions.create(
        model="ignored",
        messages=[
            {"role": "system", "content": "what do you think about these as the best sci-fi movies? do you agree?"}, 
            {"role": "user", "content":   response_text}
        ]
    )
    print(f"step 2 of {i}")

    return response


async def main():
    load_dotenv()

    client = AsyncAzureOpenAIChat(
        api_key=os.environ["OPENAI_BATCH_API_KEY"],
        api_version=os.environ["OPENAI_BATCH_API_VERSION"],
        azure_endpoint=os.environ["OPENAI_BATCH_BASE"],
        azure_deployment=os.environ["OPENAI_BATCH_MODEL"]
    )

    tasks = []

    for i in range(100):
        tasks.append(asyncio.create_task(run_experiment(client, i)))

    for t in tasks:
        result = await t
    
    logger.info("completed")
    await client._batch_processor.stop()

if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)
    logging.getLogger("evaluate.processor").setLevel(logging.DEBUG)
    # configure log output to console
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    asyncio.run(main())


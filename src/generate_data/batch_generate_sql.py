from sales_data_insights.system_message import system_message
from dotenv import load_dotenv
from openai import AzureOpenAI
import pandas as pd
import os, json, time
from sales_data_insights.system_message import system_message
import tiktoken

load_dotenv(override=True)


def upload_input_file(file_client, batch_input):
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

def submit_batch_job(batch_client, file_id):
    print("submitting batch job")
    b = batch_client.batches.create(
        input_file_id=file_id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )
    print("submitted batch job with id", b.id)
    return b.id

def monitor_and_download(batch_client, file_client, batch_id, batch_output):
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

def merge_output_write_result(questions, batch_output):
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

def count_tokens(content):
    model = "gpt-4"
    encoding = tiktoken.encoding_for_model(model)
    encoded = encoding.encode(content)
    return len(encoded)

def create_batches(questions, batch_tokens=2400000):
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
        prompt_tokens += count_tokens(str(messages))

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
        batch_input_files.append(batch_input)
        print("wrote batch input to", batch_input)
    
    return batch_input_files


def main(questions, file_id, batch_id):


    file_client = AzureOpenAI(
        api_key=os.environ["OPENAI_BATCH_API_KEY"],
        api_version=os.environ["OPENAI_BATCH_API_VERSION"],
        azure_endpoint=os.environ["OPENAI_BATCH_BASE"]
    )

    batch_client = AzureOpenAI(
        api_key=os.environ["OPENAI_BATCH_API_KEY"],
        api_version=os.environ["OPENAI_BATCH_API_VERSION"],
        azure_endpoint=os.environ["OPENAI_BATCH_BASE"],
        azure_deployment=os.environ["OPENAI_BATCH_MODEL"]
    )

    batches = create_batches(questions)
    merged_outputs = []
    for batch_input in batches:
        base = os.path.splitext(batch_input)[0]
        batch_output = f"{base}_output.jsonl"

        file_id = upload_input_file(file_client=file_client, 
                                    batch_input=batch_input)

        batch_id = submit_batch_job(batch_client, file_id)

        monitor_and_download(batch_client, file_client, batch_id, batch_output)

        merged_output = merge_output_write_result(questions, batch_output)
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



if __name__ == "__main__":
    # we need those only for local testing
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", help="the csv file containing the questions", default="src/generate_data/test_set_small.csv")
    parser.add_argument("--file_id", help="the file id of the batch input file -- if present, will skip creating the input file and use this file id instead")
    # batch_5064389a-782c-4a38-a990-997bdd4784a2
    parser.add_argument("--batch_id", help="the batch id of the batch input file -- if present, will go straight to monitoring and downloading the output file")

    args = parser.parse_args()
    
    main(args.questions, args.file_id, args.batch_id)
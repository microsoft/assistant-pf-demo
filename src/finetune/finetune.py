from sales_data_insights.system_message import system_message, system_message_compact
import pandas as pd
import os, pathlib, time
from openai import AzureOpenAI

def create_datasets(data_set, test_size=100, validation_size=40):
    # Create a dataset from the training set
    # training_set is a list of tuples (question, answer)
    # traing set looks like this:
    # { 
    #     "custom_id":"task-237",
    #     "question":"How many orders were placed on holidays last month?",
    #     "ground_truth_query":"Error: Holiday data is not available in the table"
    # }
    data_set_df = pd.read_json(data_set, lines=True)
    formatted_df = []
    for i, row in data_set_df.iterrows():
        # {"messages": 
        #   [
        #       {"role": "system", "content": "Marv is a factual chatbot that is also sarcastic."}, 
        #       {"role": "user", "content": "What's the capital of France?"}, 
        #       {"role": "assistant", "content": "Paris, as if everyone doesn't know that already."}
        #   ]
        # }

        formatted_df.append(
            {
                "messages": [
                    {"role": "system", "content": system_message_compact},
                    {"role": "user", "content": row["question"]},
                    {"role": "assistant", "content": row["ground_truth_query"]}
                ]
            }
        ) 
    finetune_df = pd.DataFrame(formatted_df)
    finetune_df = finetune_df.sample(test_size + validation_size, random_state=42)
    finetune_df.reset_index(drop=True, inplace=True) 
    validation_set = finetune_df.loc[:validation_size-1][["messages"]]
    training_set = finetune_df.loc[validation_size:][["messages"]]
    training_set.to_json("training_set.jsonl", orient="records", lines=True)
    validation_set.to_json("validation_set.jsonl", orient="records", lines=True)
    return ("training_set.jsonl", "validation_set.jsonl")

def wait_for_file(client, file_id):
    while True:
        f = client.files.retrieve(file_id)
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(current_time, file_id, "file status:", f.status)
        if f.status.lower() == "processed":
            print("file is processed")
            break
        time.sleep(2)

def submit(client, model, data_set, test_set, train_rows, validation_rows):

    training_file_name, validation_file_name = create_datasets(data_set=data_set, test_size=train_rows, validation_size=validation_rows)

    # Upload the training and validation dataset files to Azure OpenAI with the SDK.
    training_response = client.files.create(
        file=open(training_file_name, "rb"), purpose="fine-tune"
    )
    training_file_id = training_response.id

    validation_response = client.files.create(
        file=open(validation_file_name, "rb"), purpose="fine-tune"
    )
    validation_file_id = validation_response.id

    print("Training file ID:", training_file_id)
    wait_for_file(client, training_file_id)
    print("Validation file ID:", validation_file_id)
    wait_for_file(client, validation_file_id)

    # extract the file name from the data_set path
    data_set_name = os.path.basename(data_set)
    # replace . with - in the dataset name
    data_set_name = data_set_name.replace(".", "-")

    response = client.fine_tuning.jobs.create(
        training_file=training_file_id,
        validation_file=validation_file_id,
        model=model, # Enter base model name. Note that in Azure OpenAI the model name contains dashes and cannot contain dot/period characters. 
        seed = 42,  # seed parameter controls reproducibility of the fine-tuning job. If no seed is specified one will be generated automatically.
        suffix=f"{data_set_name}-{train_rows}-{validation_rows}"
    )

    job_id = response.id

    # You can use the job ID to monitor the status of the fine-tuning job.
    # The fine-tuning job will take some time to start and complete.

    print("Job ID:", response.id)
    print("Status:", response.status)
    print(response.model_dump_json(indent=2))
    return response.id

def monitor_job(client, job_id):
    job = client.fine_tuning.jobs.retrieve(job_id)
    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(current_time, "Job status:", job.status)
    printed = 0
    while True:
        job = client.fine_tuning.jobs.retrieve(job_id)
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(current_time, "Job status:", job.status)

        response = client.fine_tuning.jobs.list_events(fine_tuning_job_id=job_id)
        events = response.data.copy()
        events.reverse()
        events = events[printed:]
        printed += len(events)
        for event in events:            
            print(event)
        
        if job.status.lower() == "completed":
            print("Job completed")
            break
        time.sleep(10)

def main(model, data_set, test_set, train_rows, validation_rows, monitor):
    client = AzureOpenAI(
        azure_endpoint = os.getenv("OPENAI_API_BASE"), 
        api_key=os.getenv("OPENAI_API_KEY"),  
        api_version="2024-05-01-preview"  # This API version or later is required to access seed/events/checkpoint capabilities
    )
 
    if not monitor:
        job_id = submit(client, model, data_set, test_set, train_rows, validation_rows)
    else:
        job_id = monitor  

    monitor_job(client, job_id)    


if __name__ == '__main__':
    import argparse
    test_set = os.path.join(pathlib.Path(__file__).parent.parent.resolve(), "generate_data", "test_set_small.jsonl")
    data_set = os.path.join(pathlib.Path(__file__).parent.parent.resolve(), "generate_data", "train_set_xxl.jsonl")

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="Model to finetune", default="gpt-35-turbo-1106")
    parser.add_argument("--data_set", help="The data set to use", default=data_set)
    parser.add_argument("--test_set", help="The test set to use", default=test_set)
    parser.add_argument("--train_rows", help="Number of rows to finetune on", default=100)
    parser.add_argument("--validation_rows", help="Number of rows to finetune on", default=100)
    parser.add_argument("--monitor", help="Don't start, just monitor the job")
    args = parser.parse_args()
    main(args.model, args.data_set, args.test_set, args.train_rows, args.validation_rows, args.monitor)
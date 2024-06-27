## this script is responsible for evaluating the data from an Azure Monitor workspace.
# reads last_timestamp from timestamp-file
# executes KQL query to get the data from the Azure Monitor workspace for timestamp >= last_timestamp
#    note: the KQL query must return the fields trace_id, span_id, time_stamp
#          in addition to the fields that are required by the evaluator. 
# passes the data into evaluator to get the evaluation results.
# writes the evaluattion results as events to app insights instance.
# writes the last_timestamp back to the timestamp-file

import asyncio
import pathlib
import os, json
import pandas as pd
from datetime import datetime, timezone, timedelta
from time import time_ns
from azure.monitor.query.aio import LogsQueryClient
from azure.monitor.query import LogsQueryStatus
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import HttpResponseError
import logging
from promptflow.core import AsyncPrompty, AzureOpenAIModelConfiguration

import opentelemetry
from opentelemetry import _logs # _log is unfortunate hack that will eventually be resolved on OTel side with new Event API
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor,  ConsoleSpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace.span import TraceFlags
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor, ConsoleLogExporter
from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter, AzureMonitorTraceExporter

logger = logging.getLogger(__name__)


async def execute_kql_query(log_analytics_workspace, kql_query, last_timestamp):
    credential = DefaultAzureCredential()
    client = LogsQueryClient(credential)

    end_time=datetime.now(timezone.utc)
    start_time=last_timestamp

    logger.info(f"Executing KQL query: {kql_query}")
    logger.info(f"Start time: {start_time}")
    logger.info(f"End time: {end_time}")
    
    try:
        response = await client.query_workspace(
            workspace_id=log_analytics_workspace,
            query=kql_query,
            timespan=(start_time, end_time)
            )
        if response.status == LogsQueryStatus.PARTIAL:
            error = response.partial_error
            data = response.partial_data
            print(error)
        elif response.status == LogsQueryStatus.SUCCESS:
            data = response.tables
        for table in data:
            df = pd.DataFrame(data=table.rows, columns=table.columns)
            
    except HttpResponseError as err:
        print("something fatal happened")
        print(err)
    finally:
        await client.close()

    # make sure it has the required fields
    required_fields = ["trace_id", "span_id", "time_stamp"]
    for field in required_fields:
        if field not in df.columns:
            raise ValueError(f"Required field {field} not found in the dataframe")

    # sort dataframes by time_stamp
    df.sort_values(by="time_stamp", inplace=True)
    return df

def configure_logging(connection_string):
    provider = LoggerProvider()
    _logs.set_logger_provider(provider)

    #logger_provider.add_log_record_processor(SimpleLogRecordProcessor(OTLPLogExporter()))
    provider.add_log_record_processor(SimpleLogRecordProcessor(ConsoleLogExporter()))
    provider.add_log_record_processor(SimpleLogRecordProcessor(AzureMonitorLogExporter(connection_string=connection_string)))

def log_evaluation_event(name: str, scores: dict, meta_data: dict, message: str, dry_run=False) -> None:
    trace_id = int(meta_data["trace_id"], 16)
    span_id = int(meta_data["span_id"], 16)
    trace_flags = TraceFlags(TraceFlags.SAMPLED)
    
    attributes = {"event.name": f"gen_ai.evaluation.{name}"}
    for key, value in scores.items():
        attributes[f"gen_ai.evaluation.{key}"] = value

    event = opentelemetry.sdk._logs.LogRecord(
        timestamp=time_ns(),
        observed_timestamp=time_ns(),
        trace_id=trace_id,
        span_id=span_id,
        trace_flags=trace_flags,
        severity_text=None,
        severity_number=_logs.SeverityNumber.UNSPECIFIED,
        body=message,
        attributes=attributes
    )

    if dry_run:
        event_dict = json.loads(event.to_json()) 
        print(json.dumps(event_dict, indent=2))
    else:
        _logs.get_logger(__name__).emit(event)

async def execute_batch(prompty, batch):
    input_fields = prompty._get_input_signature().keys()
    output_fields = prompty._get_output_signature().keys()

    coros = []
    meta_data = []
    for _, row in batch.iterrows():
        inputs = {field: row[field] for field in input_fields}
        coros.append(prompty(**inputs))
        meta_data.append(dict(time_stamp=row["time_stamp"], trace_id=row["trace_id"], span_id=row["span_id"]))

    results = await asyncio.gather(*coros)
    logger.info(f"Executed batch of {len(batch)} records")
    return results, meta_data

def log_batch(name, results, meta_data, timestamp_file, dry_run=False):
    for result, meta in zip(results, meta_data):
        log_evaluation_event(name, result, meta, f"Evaluation results: {name}", dry_run=dry_run)

        # update the timestamp file
        last_timestamp = meta["time_stamp"]
        last_timestamp += timedelta(milliseconds=1) 
        if not dry_run:
            with open(timestamp_file, "w") as f:
                f.write(last_timestamp.isoformat())

async def evaluate_data(df, evaluator_path, timestamp_file, dry_run=False):
    # load the evaluator
    model_config = AzureOpenAIModelConfiguration(
        azure_endpoint=os.getenv("OPENAI_API_BASE"),
        api_key=os.getenv("OPENAI_API_KEY"),
        api_version=os.getenv("OPENAI_API_VERSION"),
        azure_deployment=os.getenv("OPENAI_EVAL_MODEL")
    )

    prompty = AsyncPrompty.load(source=evaluator_path, model={"configuration": model_config})
    input_fields = prompty._get_input_signature().keys()

    for field in input_fields:
        if field not in df.columns:
            raise ValueError(f"Required field {field} not found in the dataframe")


    # evaluate by batches of 25
    batch_size = 25
    for i in range(0, len(df), batch_size):
        batch = df.iloc[i:i+batch_size]
        results, meta_data = await execute_batch(prompty, batch)
        log_batch(name=prompty._name, 
                  results=results,
                  meta_data=meta_data, 
                  timestamp_file=timestamp_file,
                  dry_run=dry_run)

async def main(kql_file, timestamp_file, log_analytics_workspace, app_insights_connection_string, evaluator_path, dry_run=False):
    configure_logging(connection_string=app_insights_connection_string)

    last_timestamp = datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        with open(timestamp_file, "r") as f:
            last_timestamp = datetime.fromisoformat(f.read())

    except FileNotFoundError:
        pass

    with open(kql_file, "r") as f:
        kql_query = f.read()

    # Execute KQL query
    df = await execute_kql_query(log_analytics_workspace, kql_query, last_timestamp)

    logger.info(f"Query returned {len(df)} records.")

    # Evaluate the data and log the results
    await evaluate_data(df, evaluator_path, timestamp_file, dry_run=dry_run)

    
if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv(override=True)

    # dial down the logs for azure monitor -- it is so chatty
    azmon_logger = logging.getLogger('azure')
    azmon_logger.setLevel(logging.WARNING)
    # configure logging to stdout
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Evaluate Azure Monitor data")
    parser.add_argument("--kql-file", type=str, help="KQL query file. Default is sales_data_insights.kql")
    parser.add_argument("--timestamp-file", type=str, help="Timestamp file. Default is in_domain_evaluator_time_stamp.txt")
    parser.add_argument("--evaluator-path", type=str, help="Evaluator path. Currently only prompty is supported. Default is in_domain_evaluator.prompty")
    parser.add_argument("--dry-run", action="store_true", help="When set, the script will not write to App Insights. Default is False.")
    args = parser.parse_args()

    this_file = pathlib.Path(__file__).resolve()
    if not args.kql_file:
        args.kql_file = this_file.parent / "azure_monitor" / "sales_data_insights.kql"
    if not args.timestamp_file:
        args.timestamp_file = this_file.parent / "azure_monitor" / "in_domain_evaluator_time_stamp.txt"
    if not args.evaluator_path:
        args.evaluator_path = this_file.parent.parent / "custom_evaluators" / "in_domain_evaluator.prompty"
    
    if args.dry_run:
        print("\033[31m" + "Dry run mode is enabled. No data will be written to App Insights or time_stamp file." + "\033[0m")
    
    log_analytics_workspace = os.getenv("LOG_ANALYTICS_WORKSPACE_ID")
    app_insights_connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")

    print("Configuration:")
    print(f"KQL file: {args.kql_file}")
    print(f"Timestamp file: {args.timestamp_file}")
    print(f"Log Analytics Workspace: {log_analytics_workspace}")
    print(f"App Insights Key: {app_insights_connection_string}")

    asyncio.run(main(args.kql_file, args.timestamp_file, log_analytics_workspace, app_insights_connection_string, args.evaluator_path, args.dry_run))

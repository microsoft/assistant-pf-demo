import os
import logging

# local imports
from assistant_flow.core import AssistantAPI
from promptflow.tracing import start_trace, trace
from openai import AzureOpenAI
from sales_data_insights.main import SalesDataInsights
from typing import TypedDict


# You can get the same code with this link. https://aka.ms/2024-brk141​

class AssistantStream(TypedDict):

    """
    Assistant flow response. This is the output of the assistant flow and chat_completion function. 
    It contains the chat_output and session_state.

    Attributes:
        chat_output (str): The streamed output from the assistant.
        session_state (dict): The assistant thread bookkeeping.
    """

    chat_output: str
    session_state: dict


@trace
def chat_completion(
    question: str,
    session_state: dict = None,
) -> AssistantStream:

    """
    This is the entry point of Assistant flow.
    Args:
        question (str): The question to ask the assistant.
        session_state (dict, optional): The session state to resume from. Defaults to None.
        Returns: AssistantStream 
    """

    # verify all env vars are present
    required_env_vars = [
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
        "OPENAI_API_VERSION",
        "OPENAI_ASSISTANT_ID",
    ]
    missing_env_vars = []
    for env_var in required_env_vars:
        if env_var not in os.environ:
            missing_env_vars.append(env_var)

    assert (
        not missing_env_vars
    ), f"Missing environment variables: {missing_env_vars}"

    global client
    client = AzureOpenAI(
        azure_endpoint=os.getenv("OPENAI_API_BASE"),
        api_key=os.getenv("OPENAI_API_KEY"),
        api_version=os.getenv("OPENAI_API_VERSION"),
    )
    sales_data_insights = SalesDataInsights()
    
    handler = AssistantAPI(client=client,                              
                            session_state=session_state, 
                            tools=dict(sales_data_insights=sales_data_insights))
    return handler.start(question=question)

def _test():
    """Test the chat completion function."""
    # try a functions combo (without RAG)
    response = chat_completion(
        question= "Plot the order numbers and USD revenue for 2023 by month in a bar chart?"
    )

    return response


if __name__ == "__main__":
    # we need those only for local testing
    from dotenv import load_dotenv
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--env", help="Path to .env file", default=".env")
    parser.add_argument(
        "--log",
        help="Logging level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    parser.add_argument("--output", help="Output file", default="output.log")
    args = parser.parse_args()

    # turn on logging
    logging.basicConfig(
        level=args.log, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # load environment variables
    logging.debug("Loading environment variables from {}".format(args.env))
    load_dotenv(args.env, override=True)

    start_trace()

    # write tokens to output file
    with open(args.output, "w") as f:
        for token in _test()["chat_output"]:
            # write token to stream and flush
            f.write(str(token))
            f.write("\n")
            f.flush()
            


    

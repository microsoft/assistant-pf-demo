from promptflow.core import tool
from promptflow.connections import AzureOpenAIConnection
from typing import List
import os

# local imports
from chat import chat_completion

@tool
def planner(
    question: str,
    session_state: dict = {}
) -> str:
    # transforming pf connection into env vars for chat_completion
    # os.environ["OPENAI_API_BASE"] = planner_aoai_connection.api_base
    # os.environ["OPENAI_API_KEY"] = planner_aoai_connection.api_key
    # os.environ["OPENAI_ASSISTANT_ID"] = planner_assistant_id

    # just running the chat_completion function
    return chat_completion(question=question,
                           session_state=session_state)

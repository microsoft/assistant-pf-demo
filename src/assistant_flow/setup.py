# this script creates an assistant with a code interpreter and a function tool 
# to do data analytics on sales data.

import json, yaml
from dotenv import load_dotenv
from openai import AzureOpenAI
import os

load_dotenv(override=True)

def show_json(obj):
    print(json.loads(obj.model_dump_json()))

def show_yaml(obj):
    print(yaml.dump(json.loads(obj.model_dump_json()), indent=4))

print("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
print("OPENAI_API_BASE", os.getenv("OPENAI_API_BASE"))
print("OPENAI_API_VERSION", os.getenv("OPENAI_API_VERSION"))
client  = AzureOpenAI(
    api_key = os.getenv("OPENAI_API_KEY"),
    azure_endpoint = os.getenv("OPENAI_API_BASE"),
    api_version = os.getenv("OPENAI_API_VERSION")
)

tools = [
    {
        "type": "code_interpreter"
    },
    {
        "type": "function",
        "function": {
            "name": "sales_data_insights",
            "description": """
            get some data insights about the contoso sales data. This tool has information about total sales, return return rates, discounts given, etc., by date, product category, etc.
            you can ask questions like:
            - query for the month with the strongest revenue
            - which day of the week has the least sales in january
            - query the average value of orders by month
            - what is the average sale value for Tuesdays
            If you are unsure of the data available, you can ask for a list of categories, days, etc.
            - query for all the values for the main_category
            If a query cannot be answered, the tool will return a message saying that the query is not supported. otherwise the data will be returned.
            """,
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question you want to ask the tool in plain English. e.g. 'what is the average sale value for Tuesdays'",
                    }
                },
                "required": ["question"],
            },
        },
    }
]

instructions="""
You are a helpful assistant that helps the user potentially with the help of some functions.

If you are using multiple tools to solve a user's task, make sure to communicate 
information learned from one tool to the next tool.
First, make a plan of how you will use the tools to solve the user's task and communicated
that plan to the user with the first response. Then execute the plan making sure to communicate
the required information between tools since tools only see the information passed to them;
They do not have access to the chat history.
If you think that tool use can be parallelized (e.g. to get weather data for multiple cities) 
make sure to use the multi_tool_use.parallel function to execute.

Only use a tool when it is necessary to solve the user's task. 
Don't use a tool if you can answer the user's question directly.
Only use the tools provided in the tools list -- don't make up tools!!

Anything that would benefit from a tabular presentation should be returned as markup table.
"""

assistant = client.beta.assistants.create(
    name="Contoso Assistant",
    instructions=instructions,
    model=os.environ["OPENAI_ASSISTANT_MODEL"],
    tools=tools
)
show_json(assistant)
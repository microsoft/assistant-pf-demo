import json
import os
import inspect
import requests
from openai import AsyncAzureOpenAI
from urllib.parse import quote
from promptflow.core import tool
from promptflow.contracts.multimedia import Image
from promptflow.tracing import trace
import asyncio
import base64
import sqlite3
import pandas as pd

MAX_ITER = 20
global client

import json

system_message = """
### SQLite table with properties:
    #
    #  Number_of_Orders INTEGER "the number of orders processed"
    #  Sum_of_Order_Value_USD REAL "the total value of the orders processed in USD"
    #  Sum_of_Number_of_Items REAL "the sum of items in the orders processed"
    #  Number_of_Orders_with_Discount INTEGER "the number of orders that received a discount"
    #  Sum_of_Discount_Percentage REAL "the sum of discount percentage -- useful to calculate average discounts given"
    #  Sum_of_Shipping_Cost_USD REAL "the sum of shipping cost for the processed orders"
    #  Number_of_Orders_Returned INTEGER "the number of orders returned by the customers"
    #  Number_of_Orders_Cancelled INTEGER "the number or orders cancelled by the customers before they were sent out"
    #  Sum_of_Time_to_Fulfillment REAL "the sum of time to fulfillment"
    #  Number_of_Orders_Repeat_Customers INTEGER "number of orders that were placed by repeat customers"
    #  Year INTEGER
    #  Month INTEGER
    #  Day INTEGER
    #  Date TIMESTAMP
    #  Day_of_Week INTEGER in 0 based format, Monday is 0, Tuesday is 1, etc.
    #  main_category TEXT
    #  sub_category TEXT
    #  product_type TEXT
    #
In this table all numbers are already aggregated, so all queries will be some type of aggregation with group by.
for instance when asked:

Query the number of orders grouped by Month

    SELECT SUM(Number_of_Orders), 
           Month
    FROM order_data GROUP BY Month

query to get the sum of number of orders, sum of order value, average order value, average shipping cost by month

    SELECT SUM(Number_of_Orders), 
           SUM(Sum_of_Order_Value),
           SUM(Sum_of_Order_Value)/SUM(Number_of_Orders) as Avg_Order_Value,
           SUM(Sum_of_Shipping_Cost)/SUM(Number_of_Orders) as Avg_Shipping_Cost, 
           Month
    FROM order_data GROUP BY Month

whenever you get an average, make sure to use the SUM of the values divided by the SUM of the counts to get the correct average. 
The way the data is structured, you cannot use AVG() function in SQL. 

        SUM(Sum_of_Order_Value)/SUM(Number_of_Orders) as Avg_Order_Value

When asked to list categories, days, or other entities, make sure to always query with DISTICT, for instance: 
Query for all the values for the main_category

    SELECT DISTINCT main_category
    FROM order_data

Query for all the days of the week in January where the number of orders is greater than 10

    SELECT DISTINCT Day_of_Week
    FROM order_data
    WHERE Month = 1 AND Number_of_Orders > 10

If you are aked for ratios, make sure to calculate the ratio by dividing the two values and multiplying by 1.0 to force a float division. 
For instance, to get the return rate by month, you can use the following query:

    SELECT SUM(Number_of_Orders_Returned) * 1.0 / SUM(Number_of_Orders)
    FROM order_data
        
query for all the days in January 2023 where the number of orders is greater than 700

    SELECT Day, SUM(Number_of_Orders) as Total_Orders
    FROM order_data
    WHERE Month = 1 AND Year = 2023
    GROUP BY Day
    HAVING SUM(Number_of_Orders) > 700

in your reply only provide the query with no extra formatting
never use the AVG() function in SQL, always use SUM() / SUM() to get the average
                 """



@trace
async def sales_data_insights(question):
    """
    get some data insights about the contoso sales data. This tool has information about total sales, return return rates, discounts given, etc., by date, product category, etc.
    you can ask questions like:
    - query for the month with the strongest revenue
    - which day of the week has the least sales in january
    - query the average value of orders by month
    - what is the average sale value for Tuesdays
    If a query cannot be answered, the tool will return a message saying that the query is not supported. otherwise the data will be returned.
    """
    print("getting sales data insights")
    print("question", question)

    messages = [{"role": "system", 
                 "content": system_message}]
    
    messages.append({"role": "user", "content": f"{question}\nGive only the query in SQL format"})

    response = await client.chat.completions.create(
        model= os.getenv("OPENAI_CHAT_MODEL"),
        messages=messages, 
    )

    message = response.choices[0].message

    query = message.content

    ## get folder of this file -- below which is the data folder
    folder = os.path.dirname(os.path.abspath(__file__))
    con = sqlite3.connect(f'{folder}/data/order_data.db')

    try:
        df = pd.read_sql(query, con)
    except Exception as e:
        return f"Error: {e}"

    return df.to_json(orient='records')

tools = [
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

@trace
async def call_tool(tool_call, message_history, stream):
    available_functions = {
        "sales_data_insights": sales_data_insights
    }  # only one function in this example, but you can have multiple

    function_name = tool_call.function.name
    function_to_call = available_functions[function_name]
    function_args = json.loads(tool_call.function.arguments)
    await stream.send(f"calling tool {function_name} with args {function_args}\n")
    function_response = function_to_call(**function_args)
    if inspect.iscoroutinefunction(function_to_call):
        function_response = await function_response

    message_history.append(
        {
            "tool_call_id": tool_call.id,
            "role": "tool",
            "name": function_name,
            "content": function_response,
        }
    )  # extend conversation with function response

@trace
async def call_llm(message_history, stream):
    print("calling llm", message_history)
    settings = {
        "model": os.getenv("OPENAI_CHAT_MODEL"),
        "tools": tools,
        "tool_choice": "auto",
    }

    response = await client.chat.completions.create(
        messages=message_history, 
        **settings
    )

    message = response.choices[0].message
    message_history.append(message)
    if message.content:
        await stream.send(f"{message.content}\n\n---\n")

    for tool_call in message.tool_calls or []:
        if tool_call.type == "function":
            await call_tool(tool_call, message_history, stream)

    return message_history

def get(object, field):
    if hasattr(object, field):
        return getattr(object, field)
    elif hasattr(object, 'get'):
        return object.get(field)
    else:
        raise Exception(f"Object {object} does not have field {field}")

@tool
async def run_conversation(chat_history, question):
    global client
    client  = AsyncAzureOpenAI(
        api_key = os.getenv("OPENAI_API_KEY"),
        azure_endpoint = os.getenv("OPENAI_API_BASE"),
        api_version = os.getenv("OPENAI_API_VERSION")
    )

    messages = [{"role": "system", 
                 "content": """
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
                 """}]

    for turn in chat_history:
        messages.append({"role": "user", "content": turn["inputs"]["question"]})
        messages.append({"role": "assistant", "content": turn["outputs"]["answer"]})  
    
    messages.append({"role": "user", "content": question})
    image = None

    async def producer(stream, messages) -> None:
        try:
            length_of_chat = len(messages)
            cur_iter = 0
            while cur_iter < MAX_ITER:
                messages = await call_llm(messages, stream)
                message = messages[-1]
                if get(message,'role')!="tool":
                    return 

                cur_iter += 1
            await stream.send("exceeded max iterations\n")
        except Exception as e:
            await stream.send(f"Error: {e}\n")
        finally:
            await stream.end()
        return 
    
    stream = QueuedAsyncIteratorStream()
    asyncio.create_task(producer(stream, messages))
    return stream.aiter()


## move to utils
import asyncio
from typing import Any, AsyncIterator, Dict, List, Literal, Union, cast
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry import trace

class QueuedAsyncIteratorStream:
    terminate: str = "<--terminate-->"
    queue: asyncio.Queue[str]
    output: List[str]
    context_carrier: Dict[str, Any]

    def __init__(self) -> None:
        self.queue = asyncio.Queue()
        self.output = []
        self.context_carrier = {}
        # Write the current context into the carrier.
        TraceContextTextMapPropagator().inject(self.context_carrier)


    async def send(self, event: str) -> None:
        if event is not None and event != "":
            self.output.append(event)
            self.queue.put_nowait(event)

    async def end(self) -> None:
        tracer = trace.get_tracer(__name__)
        ctx = TraceContextTextMapPropagator().extract(carrier=self.context_carrier)

        with tracer.start_as_current_span("stream", context=ctx) as span:
            span.set_attribute("output", json.dumps(self.output))

        self.queue.put_nowait(self.terminate)

    async def aiter(self) -> AsyncIterator[str]:
        while True:
            # Wait for the next token in the queue,
            # but stop waiting if the done event is set
            token = await self.queue.get()

            # Cancel the other task
            if token == self.terminate:
                break

            # Otherwise, the extracted value is a token, which we yield
            yield token

async def main():
    from promptflow.tracing import start_trace
    start_trace()
    chat_history = []
    result = await run_conversation(chat_history,
                                    "what are the sales numbers for feb by category")
    
    ## iterate over the stream
    print("reading out the stream")
    async for thing in result:
        print("-"*80)
        print(thing)


if __name__ == "__main__":
    asyncio.run(main())




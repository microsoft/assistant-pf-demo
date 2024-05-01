# enable type annotation syntax on Python versions earlier than 3.9
from __future__ import annotations

import time
import json
import base64

import os
import logging
import sqlite3
import pandas as pd 

# local imports
from .core import AssistantsAPIGlue
from promptflow.tracing import start_trace, trace
from openai import AzureOpenAI

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
def sales_data_insights(question):
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

    response = client.chat.completions.create(
        model= os.getenv("OPENAI_ANALYST_CHAT_MODEL"),
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


@trace
def chat_completion(
    question: str,
    session_state: dict = {},
    context: dict[str, any] = {},
):
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

    handler = AssistantsAPIGlue(client=client, 
                                question=question, 
                                session_state=session_state, 
                                context=context, 
                                tools=dict(sales_data_insights=sales_data_insights))
    return handler.run()

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
            


    

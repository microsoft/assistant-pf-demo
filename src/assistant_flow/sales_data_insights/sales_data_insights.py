import json
import os
from openai import AzureOpenAI
from urllib.parse import quote
from promptflow.core import tool
from promptflow.contracts.multimedia import Image
from promptflow.tracing import trace
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
    #  Region TEXT
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


@tool
def sales_data_insights(question: str):
    """
    get some data insights about the contoso sales data. This tool has information about total sales, return return rates, discounts given, etc., by date, product category, etc.
    you can ask questions like:
    - query for the month with the strongest revenue
    - which day of the week has the least sales in january
    - query the average value of orders by month
    - what is the average sale value for Tuesdays
    If a query cannot be answered, the tool will return a message saying that the query is not supported. otherwise the data will be returned.
    """

    client  = AzureOpenAI(
        api_key = os.getenv("OPENAI_API_KEY"),
        azure_endpoint = os.getenv("OPENAI_API_BASE"),
        api_version = os.getenv("OPENAI_API_VERSION")
    )

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
        return {"data": None, "error": f"{e}", "query": query}

    data = df.to_dict(orient='records')
    return {"data": data, "error": None, "query": query}

 
def main():
    from promptflow.tracing import start_trace
    start_trace()
    result = sales_data_insights(question="what are the sales numbers aggregated by country for feb by category")
    print(json.dumps(result, indent=4))

if __name__ == "__main__":
    main()




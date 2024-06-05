import os
import pathlib
import sqlite3
from openai import AsyncAzureOpenAI
import pandas as pd
from promptflow.tracing import trace
import json
from azure.ai.inference.aio import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from sales_data_insights.system_message import system_message, system_message_short
import asyncio
from typing import TypedDict

class Result(TypedDict):
    data: dict
    error: str
    query: str
    execution_time: float

# Callable class with @trace decorator on the __call__ method
class SalesDataInsights:

    """
    SalesDataInsights tool. You can use this tool as a standalone flow to retrieve sales data
    with natural language queries. In this example, it's also called by the assistant API for a
    full end-to-end assistant experience.
    """

    def __init__(self, data=None, model_type="azure_openai"):
        self.data = data if data else os.path.join(
            pathlib.Path(__file__).parent.resolve(), "data", "order_data.db"
        )
        self.model_type = model_type
        if self.model_type == "azure_openai":
            self.client = AsyncAzureOpenAI(
                                api_key = os.getenv("OPENAI_API_KEY"),
                                azure_endpoint = os.getenv("OPENAI_API_BASE"),
                                api_version = os.getenv("OPENAI_API_VERSION")
                            )
        else:
            endpoint = os.getenv(f"AZUREAI_{self.model_type.upper()}_URL")
            key = os.getenv(f"AZUREAI_{self.model_type.upper()}_KEY")
            print("endpoint", endpoint)
            print("key", key)
            self.client = ChatCompletionsClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(key),
            )

    @trace
    async def __call__(self, *, question: str, **kwargs) -> Result:

        # Code to get time to execute the function
        import time
        start = time.time()
        
        print("getting sales data insights")
        print("question", question)

        if self.model_type == "azure_openai":
            messages = [{"role": "system", "content": system_message}]
        
            messages.append({"role": "user", "content": f"{question}\nGive only the query in SQL format"})

            response = await self.client.chat.completions.create(
                model= os.getenv("OPENAI_ANALYST_CHAT_MODEL"),
                messages=messages, 
            )
        elif self.model_type.lower() == "phi3_mini":
            combined_message = UserMessage(content=f"{system_message_short}\n\n{question}\nGive only the query in SQL format")
            messages = [combined_message]
            response = await self.client.create(messages=messages, temperature=0, max_tokens=1000)
        elif self.model_type.lower() == "phi3_medium":
            combined_message = UserMessage(content=f"{system_message}\n\n{question}\nGive only the query in SQL format")
            messages = [combined_message]
            response = await self.client.create(messages=messages, temperature=0, max_tokens=1000)
        else:
            system_message_obj = SystemMessage(content=system_message)
            user_message_obj = UserMessage(content=f"{question}\nGive only the query in SQL format")
            messages = [system_message_obj, user_message_obj]
            response = await self.client.create(messages=messages, temperature=0, max_tokens=1000)

        message = response.choices[0].message

        query :str = message.content

        if query.startswith("```sql") and query.endswith("```"):
            query = query[6:-3].strip()

        if query.lower().startswith("error"):
            end = time.time()
            execution_time = round(end - start, 2)
            return {"data": None, "error": query, "query": query, "execution_time": 0}
        
        try:
            data = self.query_db(query)
        except Exception as e:
            end = time.time()
            execution_time = round(end - start, 2)
            print("Execution time:", execution_time)
            return {"data": None, "error": f"{e}", "query": query, "execution_time": execution_time}

        end = time.time()
        execution_time = round(end - start, 2)

        return {"data": data, "error": str(None), "query": query, "execution_time": execution_time}
    
    @trace
    def query_db(self, query: str) -> dict:
        sql_connection = sqlite3.connect(self.data)

        df = pd.read_sql(query, sql_connection)

        return df.to_dict(orient='records')

    async def close(self):
        await self.client.close()
    
    async def __aenter__(self):
        print("entering")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("exiting")
        await self.close()
 
async def main():
    models = ["azure_openai", "phi3_mini", "phi3_medium", "cohere_chat", "mistral_small", "mistral_large", "llama3"]

    for model in models:
        print("="*50)
        print("model", model)
        async with SalesDataInsights(model_type=model) as sdi:
            result = await sdi(question="for 2024 Query the average number of orders per day grouped by Month")
            result["data"] = None
        print("execution_time:", result['execution_time'])
        print("query", result['query'])

if __name__ == "__main__":
    asyncio.run(main())
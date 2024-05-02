# Project

## Tracing function calls

In this sample, we will show how to use [Azure OpenAI Assistants](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/assistant) with [Prompt Flow](https://microsoft.github.io/promptflow/).

### Prerequisites:

- Python 3.11
- Conda
- AI Studio Hub & Project with an Azure OpenAI endpoint (**OPENAI_API_BASE**, **OPENAI_API_KEY**) in a [region that supports assistants](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models#assistants-preview) with an 1106 model or better -- I recommend creating it in Sweden central. 
- Deployments of OpenAI models:
    - deployment of `gpt-4-1106-preview`/`gpt-35-turbo-1106` or later for use by the **OpenAI assistant**. Both work, but `gpt-35-turbo-1106` is faster and `gpt-4-1106-preview` is more accurate. (**OPENAI_ASSISTANT_MODEL**)
    - deployment of `gpt-35-turbo-1106` or later for use by the **Data Analyst** to perform some limited NL to SQL. (**OPENAI_ANALYST_CHAT_MODEL**)
- Azure Application Insights (**APPINSIGHTS_INSTRUMENTATIONKEY**)

Copy `.env.sample` to `.env` and fill in the values:

```bash
OPENAI_API_TYPE="azure"
OPENAI_API_VERSION="2024-02-15-preview"
OPENAI_API_BASE="https://***.openai.azure.com/"
OPENAI_API_KEY="******************"
OPENAI_ASSISTANT_MODEL="gpt-35-turbo-1106"
OPENAI_ANALYST_CHAT_MODEL="gpt-35-turbo-1106"
OPENAI_ASSISTANT_ID="asst_0leWabwuOmzsNVG5Kst1CpeV" <-- you will create this further down
APPINSIGHTS_INSTRUMENTATIONKEY="InstrumentationKey=***;IngestionEndpoint=https://****.in.applicationinsights.azure.com/;LiveEndpoint=https://****"
```

### Install dependencies

```bash
conda env create -f environment.yml
conda activate assistant
```

Then install the pre-release version of azure-monitor-opentelemetry-exporter
```bash
pip install azure-monitor-opentelemetry-exporter --pre
```

### Create an OpenAI assistant

Create an OpenAI assistant using the setup.py script

```bash
python src/assistant_flow/setup.py
```

This should ouput something like this:

```log
OPENAI_API_KEY ******
OPENAI_API_BASE https://******.openai.azure.com
OPENAI_API_VERSION 2024-02-15-preview
{'id': 'asst_wgEXCRBQ7E4BfznSkGgJy41k', 'created_at': 1714610540, 'description': None, 'instructions': "\nYou are a helpful assistant that helps the user potentially with the help of some functions.\n\nIf you are using multiple tools to solve a user's task, make sure to communicate \ninformation learned from one tool to the next tool.\nFirst, make a plan of how you will use the tools to solve the user's task and communicated\nthat plan to the user with the first response. Then execute the plan making sure to communicate\nthe required information between tools since tools only see the information passed to them;\nThey do not have access to the chat history.\nIf you think that tool use can be parallelized (e.g. to get weather data for multiple cities) \nmake sure to use the multi_tool_use.parallel function to execute.\n\nOnly use a tool when it is necessary to solve the user's task. \nDon't use a tool if you can answer the user's question directly.\nOnly use the tools provided in the tools list -- don't make up tools!!\n\nAnything that would benefit from a tabular presentation should be returned as markup table.\n", 'metadata': {}, 'model': 'gpt-35-turbo-1106', 'name': 'Contoso Assistant', 'object': 'assistant', 'tools': [{'type': 'code_interpreter'}, {'function': {'name': 'sales_data_insights', 'description': '\n            get some data insights about the contoso sales data. This tool has information about total sales, return return rates, discounts given, etc., by date, product category, etc.\n            you can ask questions like:\n            - query for the month with the strongest revenue\n            - which day of the week has the least sales in january\n            - query the average value of orders by month\n            - what is the average sale value for Tuesdays\n            If you are unsure of the data available, you can ask for a list of categories, days, etc.\n            - query for all the values for the main_category\n            If a query cannot be answered, the tool will return a message saying that the query is not supported. otherwise the data will be returned.\n            ', 'parameters': {'type': 'object', 'properties': {'question': {'type': 'string', 'description': "The question you want to ask the tool in plain English. e.g. 'what is the average sale value for Tuesdays'"}}, 'required': ['question']}}, 'type': 'function'}], 'response_format': None, 'temperature': None, 'tool_resources': None, 'top_p': None, 'file_ids': []}
Assistant created with id asst_wgEXCRBQ7E4BfznSkGgJy41k
add the following to your .env file
OPENAI_ASSISTANT_ID="asst_wgEXCRBQ7E4BfznSkGgJy41k"
```

You should go to your Azure AI Studio project and check that the assistant was actually created -- it should look like this:
<img src="images/assistant-ai-studio.png" width="800">

Then do as instructed suggested on the console by adding the provided line `OPENAI_ASSISTANT_ID="asst_*****"` to the `.env` file.


### Run the sample

The sample app uses [chainlit](https://docs.chainlit.io/get-started/overview) to build a simple chat UI that is capable of displaying images. The app is started like so:

```bash
cd src
python app.py
```

The console output will be similar to this (port numbers might differ):

```bash
INFO:waitress:Serving on http://127.0.0.1:61802
Start Prompt Flow Service on 61802, version: 1.7.0
You can view the traces from local: http://localhost:61802/v1.0/ui/traces/
2024-03-30 11:15:14 - Request URL: 'https://dc.services.visualstudio.com/v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '2020'
    'Accept': 'application/json'
    'x-ms-client-request-id': '54367e9e-ee7e-11ee-a580-0e3a2dccaa78'
    'User-Agent': 'azsdk-python-azuremonitorclient/unknown Python/3.10.4 (macOS-10.16-x86_64-i386-64bit)'
A body is sent with the request
2024-03-30 11:15:14 - Your app is available at http://localhost:8000
```

Open two browser tabs, one to `http://localhost:8000` and one to `http://localhost:61802/v1.0/ui/traces/`


## Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft 
trademarks or logos is subject to and must follow 
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.

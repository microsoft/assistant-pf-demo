# Assistant Demo!

This is a simple demo of using the OpenAI Assistant API to create a chatbot. The assistant has access to two tools:
1. A function to query the 2023 sales data for Contoso.
1. A code interpreter, which it will use to make graphs of the sales data.

Test it by asking the assistant some questions about the sales data, for instance:
- show the 2023 sales by category in a bar chart
- show the total sales revenue aggregated by year and month in a line chart
- show the total sales revenue for May 2024
    - break it down by day and show it to me in a line chart
    - break it down by day and by catgory and show it in a multi-series bar chart
    - show the same in a multi-series line chart


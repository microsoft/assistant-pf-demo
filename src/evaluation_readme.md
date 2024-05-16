# Evaluation

## Evaluators

Evaluators can be found [here](./custom_evaluators/)

| Evaluator | Description |
|----------|----------|
|   [SQLSimilarityEvaluator](./custom_evaluators/sql_similarity/)  |   Compares two SQL queries for similarity using LLM  |
|   [CompareEvaluator](./custom_evaluators/compare.py)  |   Compares two SQL queries to be strictly the same  |

## Application to be Evaluated
Application to be evaluated is [Sales Data Insight](./sales_data_insights/)

## How to Evaluate ?

To evaluate run the following command:

```bash
python src/evaluation.py
```
This should output results in tabular form, average scores and `AI Studio URL` where evaluation results can be seen easily seen for comparison

```log
'-----Tabular Results-----'
                                        outputs.data                                      outputs.error  ... outputs.execution_time.seconds  line_number
0  [{'Day': 1, 'Total_Orders': 35}, {'Day': 2, 'T...                                               None  ...                           3.06            0
1  [{'product_type': 'JACKETS & VESTS'}, {'produc...                                               None  ...                           1.10            1
2               [{'Total_Revenue': 2517.6189987606}]                                               None  ...                           2.52            2
3                                           (Failed)  Execution failed on sql 'SELECT SUM(Sum_of_Ord...  ...                           3.40            3
4  [{'Day': 1, 'sub_category': 'MEN'S FOOTWEAR', ...                                               None  ...                           2.87            4

[5 rows x 11 columns]

'-----Average of Scores-----'
{'compare.score': 0.0,
 'execution_time.seconds': 2.59,
 'sql_similarity.score': 3.8}

-----Studio URL-----
'https://ai.azure.com/build/evaluation/assistant_pf_demo_variant_0_20240509_143418_546676?wsid=/subscriptions/e0fd569c-e34a-4249-8c24-e8d723c7f054/resourceGroups/rg-qunsongai/providers/Microsoft.MachineLearningServices/workspaces/qunsong-0951'
```

Clicking on Studio URL will take you to `AI Studio` where comparison can be done easily


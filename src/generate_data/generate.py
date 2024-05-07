import pandas as pd
import numpy as np

def generate_order_data(num_rows, boost):
    # Generate 'Number_of_Orders' first to use as a base for constraints
    number_of_orders = np.int32(np.random.randint(0, 10, num_rows) * boost/10)
    number_of_orders = np.maximum(number_of_orders, 1)
    # for the rows that have number_of_orders == 1, introduce a random chance to increase the number of orders
    for i in range(num_rows):
        if number_of_orders[i] == 1:
            if np.random.random() < 0.1:
                number_of_orders[i] = 2
    # Define averages for scalability
    average_order_value = 30 * 1/boost  # Average order value per order
    items_per_order = 3.5     # Average number of items per order
    shipping_cost_per_order = 7.5  # Average shipping cost per order
    time_per_order = 1.5     # Average fulfillment time per order

    # Generate other columns with normal distribution based on 'Number_of_Orders'
    data = {
        "Number_of_Orders": number_of_orders,
        "Sum_of_Order_Value_USD": np.abs(np.random.normal(average_order_value, 5, num_rows)) * number_of_orders,
        "Sum_of_Number_of_Items": np.abs(np.floor(np.random.normal(items_per_order, 3, num_rows))) * number_of_orders,
        "Number_of_Orders_with_Discount": np.random.randint(0, number_of_orders + 1),
        "Sum_of_Discount_Percentage": np.random.uniform(0.1, 1, num_rows) * 100,  # Constant range for percentage
        "Sum_of_Shipping_Cost_USD": np.abs(np.random.normal(shipping_cost_per_order, 2, num_rows)) * number_of_orders,
        "Number_of_Orders_Returned": np.random.randint(0, number_of_orders + 1),
        "Number_of_Orders_Cancelled": np.random.randint(0, number_of_orders + 1),
        "Sum_of_Time_to_Fulfillment": np.random.normal(time_per_order, 0.5, num_rows) * number_of_orders,
        "Number_of_Orders_Repeat_Customers": np.random.randint(0, number_of_orders + 1)
    }

    return pd.DataFrame(data)

def save_to_csv(df, filename="data/order_data.csv"):
    # Save the DataFrame to a CSV file
    df.to_csv(filename, index=False)
    print(f"Data saved to {filename}")

def save_to_sql(df, filename="data/order_data.db"):
    import sqlite3
    conn = sqlite3.connect(filename)
    df.to_sql("order_data", conn, if_exists="replace", index=False)
    conn.close()
    print(f"Data saved to {filename}")

# read in product categories
import os
current_dir = os.path.dirname(os.path.realpath(__file__))
product_categories = pd.read_csv(f"{current_dir}/product_categories.csv")
num_categories = len(product_categories)

regions = ["North America", "Europe", "Asia-Pacific", "Africa", "Middle East", "South America"]
regions = [region.upper() for region in regions]

num_regions = len(regions)

start_date = pd.to_datetime('2023-01-01')
end_date = pd.to_datetime('2024-05-21')
# end_date = pd.to_datetime('2023-01-03')
num_days = (end_date - start_date).days
total_data = pd.DataFrame()

for region_index in range(num_regions):
    # generate order data for each day
    for i in range(num_days):
        order_day = start_date + pd.DateOffset(days=i)
        boost1 = (10 + order_day.dayofweek + 10 * (i/num_days)) / 10
        boost2 = (0.2 * np.sin(i/90 * 2 * np.pi) + 1)
        boost3 = (10-region_index) / 10
        boost = boost1 * boost2 * boost3
        #print(f"boost: {boost:.2f}, {boost1:.2f}, {boost2:.2f}, {boost3:.2f} on {order_day.dayofweek}, i={i}, region {regions[region_index]}")
        order_data = generate_order_data(num_categories, boost)
        order_data['Year'] = order_day.year
        order_data['Month'] = order_day.month
        order_data['Day'] = order_day.day
        order_data['Date'] = order_day
        order_data['Day_of_Week'] = order_day.dayofweek
        
        # bring product categories and order data together
        # in the end we will have a table with product categories and order data
        for col in product_categories.columns:
            order_data[col] = product_categories[col]
        order_data['Region'] = regions[region_index]

        total_data = pd.concat([total_data, order_data], ignore_index=True)

save_to_sql(total_data, filename=f"{current_dir}/../assistant_flow/sales_data_insights/data/order_data.db")

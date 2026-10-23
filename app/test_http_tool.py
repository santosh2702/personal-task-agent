from app.main import fetch_api_data

url = "https://jsonplaceholder.typicode.com/todos/1"

try:
    result = fetch_api_data(url)
    print("API call successful!")
    print(result)

except Exception as error:
    print(f"API call failed: {error}")
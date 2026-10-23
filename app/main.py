import os
import json
import ast
import operator

import sqlite3
import uuid
from pathlib import Path

import httpx

import time
import random

from playwright.sync_api import sync_playwright
from urllib.parse import quote_plus

from dotenv import load_dotenv
from groq import Groq

TOOLS_REQUIRING_APPROVAL = {
    "delete_file",
}

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


# Tool: Performs supported calculations
def calculate(expression):
    operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    def evaluate(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value

        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            left = evaluate(node.left)
            right = evaluate(node.right)
            return operators[type(node.op)](left, right)

        raise ValueError("Unsupported expression")
    return evaluate(ast.parse(expression, mode="eval").body)
    


# Tool description provided to the LLM
tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Perform a supported mathematical calculation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "A mathematicalexpression using numbers and +, -, *, / operators.",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
    {
    "type": "function",
    "function": {
        "name": "play_on_youtube",
        "description": "Search YouTube and play a song requested by the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "song": {
                    "type": "string",
                    "description": "The song name and artist to search for on YouTube."
                }
            },
            "required": ["song"],
            "additionalProperties": False
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "delete_file",
        "description": "Delete a file. This action requires human approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the file to delete"
                }
            },
            "required": ["filename"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "fetch_api_data",
        "description": (
            "Fetch JSON data from a trusted HTTP API URL "
            "when the user requests data from an API."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the HTTP API endpoint."
                }
            },
            "required": ["url"],
            "additionalProperties": False
        }
    }
}
]

def delete_file(filename: str):
    return f"SIMULATION: File '{filename}' would be deleted."

def play_on_youtube(song: str):
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="./chrome_profile",
            channel="chrome",
            headless=False,
        )

        page = context.pages[0] if context.pages else context.new_page()

        search_url = (
            "https://www.youtube.com/results?search_query="
            + quote_plus(song)
        )
        page.goto(search_url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        video = page.locator(
            "ytd-video-renderer a#video-title"
        ).first

        video.wait_for(state="visible", timeout=20000)
        video.click()

        print(f"Playing on Youtube: {song}")
        input("Press Enter to stop an dclose the browser...")

        context.close()


def request_approval(tool_name, arguments):
    print("\nHuman approval required")
    print(f"Action: {tool_name}")
    print(f"Arguments: {arguments}")

    decision = input("Approve this action? (yes/no): ")
    return decision.strip().lower() == "yes"

DB_PATH = "agent_state.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        tool_name TEXT NOT NULL,
        arguments TEXT NOT NULL,
        status TEXT NOT NULL
        )
        """)

def save_pending_approval(tool_name, arguments):
    approval_id = str(uuid.uuid4())

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO approvals (id, tool_name, arguments, status)
            VALUES (?,?,?,?)
            """,
            (
                approval_id,
                tool_name,
                json.dumps(arguments),
                "pending",
            ),
        )
    return approval_id

def create_approval_request(tool_name, arguments):
    approval_id = save_pending_approval(tool_name, arguments)

    print("\n⏸️ Agent paused — human approval required")
    print(f"Approval ID: {approval_id}")
    print(f"Action: {tool_name}")
    print(f"Arguments: {arguments}")
    print("\nApprove or reject this request later using its ID.")

    return approval_id


def decide_approval(approval_id, decision):
    if decision not in ("approved", "rejected"):
        raise ValueError("Decision must be 'approved' or 'rejected'")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE approvals
            SET status = ?
            WHERE id = ? AND status = 'pending'
            """,
            (decision, approval_id),
        )

        if cursor.rowcount == 0:
            existing = conn.execute(
                "SELECT status FROM approvals WHERE id = ?",
                (approval_id,),
            ).fetchone()

            if existing is None:
                return "Approval request not found."

            return f"Request already processed. Current status: {existing[0]}"

    return f"Request {decision} successfully."


def execute_approved_action(approval_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT tool_name, arguments, status
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        if row is None:
            return "Approval request not found."

        tool_name, arguments_json, status = row

        if status != "approved":
            return f"Action cannot execute. Current status: {status}"

        arguments = json.loads(arguments_json)

        # Allow only explicitly approved tools.
        if tool_name == "delete_file":
            result = delete_file(**arguments)
        else:
            return f"Unsupported approved tool: {tool_name}"

        # Mark the request as completed.
        cursor = conn.execute(
            """
            UPDATE approvals
            SET status = 'completed'
            WHERE id = ? AND status = 'approved'
            """,
            (approval_id,),
        )

        if cursor.rowcount == 0:
            return "Action was not marked completed."

    return result



def retry_operation(
    operation,
    retryable_exceptions,
    should_retry=None,
    max_attempts=3,
):
    for attempt in range(max_attempts):
        try:
            return operation()

        except retryable_exceptions as error:
            if should_retry is not None and not should_retry(error):
                raise

            if attempt == max_attempts - 1:
                raise

            delay = (2 ** attempt) + random.uniform(0, 0.5)

            print(
                f"Attempt {attempt + 1} failed. "
                f"Retrying in {delay:.2f} seconds..."
            )

            time.sleep(delay)

def fetch_api_data(url: str):
    retryable_status_codes = {429, 500, 502, 503, 504}

    def make_request():
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

    def should_retry(error):
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in retryable_status_codes

        return True

    return retry_operation(
        operation=make_request,
        retryable_exceptions=(
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.HTTPStatusError,
        ),
        should_retry=should_retry,
        max_attempts=3,
    )


def create_plan(goal):
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a task planner. "
                    "Break the user's goal into 2-5 simple, "
                    "ordered steps. Keep steps actionable. "
                    "Use existing tools when appropriate. "
                    "Do not execute the steps. Only create the plan."
                ),
            },
            {"role": "user", "content": goal},
        ],
        tool_choice="none",
    )

    return response.choices[0].message.content


def verify_tool_result(tool_name, result):
    """Check whether a tool result indicates success or failure."""

    result_text = str(result).lower()

    failure_indicators = [
        "error",
        "failed",
        "exception",
        "timed out",
        "not found",
    ]

    if any(indicator in result_text for indicator in failure_indicators):
        return {
            "verified": False,
            "message": f"{tool_name} did not report success. Result: {result}",
        }

    if tool_name == "delete_file" and "simulation" in result_text:
        return {
            "verified": False,
            "message": "Deletion was simulated; no file was actually deleted.",
        }

    return {
        "verified": True,
        "message": f"{tool_name} returned a result without an obvious failure.",
    }


def main():
    print("Working directory:", Path.cwd())
    print("Database path:", Path(DB_PATH).resolve())
    init_db()

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. "
                "Use the calculate tool for mathematical calculations. "
                "When the user asks to play a song on YouTube, you MUST "
                "call play_on_youtube. "
                "Never claim a tool succeeded unless it was executed. "
                "Explain results clearly. "
                "When the user requests file deletion, you MUST call "
                "the delete_file tool. Never ask for approval yourself; "
                "the Python application handles human approval. "
                "When the user requests data from an HTTP API, "
                "use the fetch_api_data tool. "
                "Never claim the request succeeded unless the tool "
                "returns a successful result."
            ),
        }
    ]

    while True:
        goal = input("\nYou (type 'exit' to quit): ").strip()

        if goal.lower() == "exit":
            print("Agent: Goodbye!")
            break

        if not goal:
            continue

        plan = create_plan(goal)

        print("\nAgent Plan:")
        print(plan)

        messages.append({
                "role": "user",
                "content": (
                f"My goal: {goal}\n\n"
                f"My execution plan:\n{plan}\n\n"
                "Work through this plan using your available tools. "
                "Follow the steps in order and report the results honestly."
    ),
})

        failed_tools = set()

        # Agent execution loop
        for iteration in range(5):
            response = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

            message = response.choices[0].message
            print("Tool calls:", message.tool_calls)

            # Save the LLM response
            messages.append(message)

            # No tool requested: return the final answer
            if not message.tool_calls:
                print("\nAgent:", message.content)
                break

            # Execute every requested tool
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                # Human-in-the-loop approval
                if tool_name in TOOLS_REQUIRING_APPROVAL:
                    approval_id = create_approval_request(
                        tool_name,
                        arguments,
                    )

                    result = (
                        f"Action paused for approval. "
                        f"Approval ID: {approval_id}. "
                        "The action has not been executed."
                    )

                    print(result)

                    
                    verification = verify_tool_result(tool_name, result)

                    print("\nVerification:", verification["message"])

                    messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": (
                                        f"Tool result: {result}\n"
                                        f"Verification: {verification['message']}"
    ),
                    })

                    continue

                # Prevent repeated attempts after a tool failure
                if tool_name in failed_tools:
                    result = (
                        f"Tool '{tool_name}' already failed. "
                        "Do not retry it."
                    )

                    print(result)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                    continue

                print(f"\nExecuting tool: {tool_name}")

                if tool_name == "calculate":
                    try:
                        result = calculate(arguments["expression"])
                    except (
                        ValueError,
                        ZeroDivisionError,
                        SyntaxError,
                        TypeError,
                        KeyError,
                    ) as error:
                        failed_tools.add(tool_name)
                        result = f"Calculation failed: {error}"

                elif tool_name == "play_on_youtube":
                    try:
                        play_on_youtube(arguments["song"])
                        result = (
                            "YouTube playback was opened for: "
                            f"{arguments['song']}"
                        )
                    except Exception as error:
                        failed_tools.add(tool_name)
                        result = f"YouTube playback failed: {error}"

                elif tool_name == "fetch_api_data":
                    try:
                        api_result = fetch_api_data(arguments["url"])
                        result = json.dumps(api_result)
                    except Exception as error:
                        failed_tools.add(tool_name)
                        result = f"API request failed: {error}"

                else:
                    result = f"Unknown tool: {tool_name}"

                print(f"Tool result: {result}")

                # Return the tool result to the LLM
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                })

        else:
            print("Agent stopped: maximum iterations reached.")



if __name__ == "__main__":
    main()
# 🤖 Agent Forge

> A beginner-friendly task agent built with Python and Groq. Learn how
> planning, tool calling, retries, session memory, human approval, and
> basic result checks fit together.

Agent Forge accepts a goal in natural language, creates a plan, selects
tools when useful, executes tool calls, and returns a response. It is a
learning project: the implementation is intentionally small enough to
follow from beginning to end.

## ✨ Features

-   🧠 **Planning:** breaks a goal into ordered steps.
-   🛠️ **Tool calling:** lets the model request Python functions.
-   ➕ **Calculator:** evaluates basic arithmetic using a restricted AST
    evaluator.
-   🌐 **API fetching:** calls an HTTP endpoint and returns JSON.
-   ▶️ **YouTube automation:** uses Playwright to search for a video and
    attempt playback.
-   🛑 **Human-in-the-loop (HITL):** pauses approval-gated actions.
-   🔁 **Retries:** retries selected transient errors with exponential
    backoff and jitter.
-   💬 **Session memory:** keeps conversation history while the process
    is running.
-   ✅ **Basic result verification:** looks for obvious failure
    indicators in tool output.
-   🗄️ **SQLite state:** stores approval requests.

### Current limitations

-   Most logic currently lives in `app/main.py`; this README does not
    imply the project already has separate modules for every feature.
-   Conversation memory is lost when the application restarts.
-   `delete_file` is a **simulation** and does not delete an actual
    file.
-   HITL records approval decisions, but the original agent task does
    not automatically resume after approval.
-   Result verification is heuristic; it cannot prove an external action
    truly succeeded.
-   Browser automation may fail because of site changes, consent
    dialogs, browser state, or playback restrictions.

------------------------------------------------------------------------

## 🧱 Architecture at a glance

``` mermaid
flowchart TD
    A[User enters goal] --> B[Planner creates steps]
    B --> C[Goal and plan added to messages]
    C --> D[LLM decides next action]
    D --> E{Tool call?}
    E -- No --> F[Display final answer]
    E -- Yes --> G[Parse tool arguments]
    G --> H{Approval required?}
    H -- Yes --> I[Save approval in SQLite]
    I --> J[Pause and tell user approval is required]
    H -- No --> K[Execute Python tool]
    K --> L[Retry selected transient failures]
    L --> M[Basic result check]
    M --> N[Send tool result back to LLM]
    N --> D
```

**Core idea:** the LLM chooses the next step, but Python executes the
actual function. The tool result is returned to the LLM so it can
continue or produce a final answer.

## 📁 Project structure

The current checkout is expected to look approximately like this:

``` text
personal-task-agent/
├── app/
│   └── main.py          # Most current agent logic lives here
├── .env                 # Local API key; never commit this
├── .gitignore           # Excludes secrets and local/runtime files
├── agent_state.db       # SQLite approval state, created at runtime
├── chrome_profile/      # Persistent Playwright browser profile
└── README.md
```

Some files and directories are created only after running the app. Your
exact checkout may differ.

### Possible future modular structure

If the project grows, you could refactor it into smaller modules:

``` text
app/
├── main.py              # Entry point and agent loop
├── planner.py           # create_plan()
├── tools/
│   ├── calculator.py    # calculate()
│   ├── api.py           # fetch_api_data()
│   └── youtube.py       # play_on_youtube()
├── safety/
│   └── approvals.py     # HITL approval workflow
├── memory/
│   └── session.py       # Conversation history
└── verification.py      # verify_tool_result()
```

This is a **suggested future design, not the current file layout**. Do
not create these files unless you move the functions and update imports.

------------------------------------------------------------------------

## 🚀 Getting started

### Prerequisites

-   Python version compatible with the dependencies in your environment
    (Python 3.10+ is a reasonable baseline).
-   A Groq API key.
-   A terminal.
-   Chrome/Chromium and Playwright setup if you want to test the YouTube
    tool.

### 1. Open the project

``` bash
cd /path/to/personal-task-agent
```

During development, the local path was
`/Users/santoshkumar/personal-task-agent`; replace it with your own
path.

### 2. Activate your virtual environment

For a `.venv` environment on macOS/Linux:

``` bash
source .venv/bin/activate
```

Use the actual environment directory name if yours is different.

### 3. Configure `.env`

Create or update `.env` in the project root:

``` dotenv
GROQ_API_KEY=your_groq_api_key_here
```

Never publish your real key. Ensure `.env` is included in `.gitignore`.

### 4. Install dependencies

If the project contains a `requirements.txt`:

``` bash
pip install -r requirements.txt
```

If it does not, inspect the imports in `app/main.py` and create a
dependency list from the working environment. Avoid guessing package
versions; pin versions after confirming they work.

### 5. Run Agent Forge

``` bash
python app/main.py
```

Enter a goal at the prompt. Type `exit` to stop the application.

------------------------------------------------------------------------

## 🔍 Code walkthrough: follow the current implementation

Most of the following responsibilities are implemented in `app/main.py`.
The names below correspond to the functions and code patterns in the
current working version.

### 1. Configuration and Groq client

**Purpose:** load environment variables and initialize the model client.

Look for `load_dotenv()`, the `GROQ_API_KEY` configuration, and the
`Groq` client initialization. The current working model is
`openai/gpt-oss-20b`.

The client sends messages to the LLM. The LLM can answer directly or
request one of the tools described by the tool schemas.

**Debugging tip:** if the API request fails, first check that the key is
configured and that the model name is available to your account.

### 2. Tool schemas (`tools`)

**Purpose:** describe available tools and their arguments to the model.

The current schemas include:

  Tool                Purpose                           Typical argument
  ------------------- --------------------------------- ------------------
  `calculate`         Evaluate arithmetic               `expression`
  `fetch_api_data`    Fetch a URL and return JSON       `url`
  `play_on_youtube`   Search for a song/video           `song`
  `delete_file`       Simulated deletion, behind HITL   `filename`

A schema tells the model **how to request** a tool. It does not
implement the function. The Python function and the dispatch branch are
responsible for execution.

**When debugging:** compare the schema's argument names with the Python
function signature and the JSON arguments. A mismatch can cause a
tool-call validation error.

### 3. Calculator (`calculate(expression)`)

**Purpose:** evaluate a limited set of arithmetic expressions.

The calculator parses expressions with Python's Abstract Syntax Tree
(AST) and allows specific numeric operations, such as `+`, `-`, `*`, and
`/`.

A restricted AST evaluator is safer than evaluating arbitrary
model-generated text with `eval()`, because it can reject unsupported
syntax.

Try these prompts:

``` text
Calculate 12 * 8
Calculate (25 + 5) / 2
Calculate 10 / 0
```

The last prompt should be handled as a controlled calculation error
rather than terminating the whole application.

### 4. API tool (`fetch_api_data(url)`)

**Purpose:** make an HTTP GET request and return the JSON response.

The current implementation uses `httpx.Client(timeout=10.0)`, calls
`raise_for_status()`, and returns the decoded JSON. Selected transient
failures, such as timeouts and HTTP 429/5xx responses, can be retried.

Example prompt:

``` text
Fetch https://jsonplaceholder.typicode.com/todos/1
```

Example response:

``` json
{
  "userId": 1,
  "id": 1,
  "title": "delectus aut autem",
  "completed": false
}
```

**Security note:** unrestricted URL fetching can expose internal
services or network locations. If the agent is used beyond local
learning, validate URLs and restrict which hosts it may access.

### 5. YouTube automation (`play_on_youtube(song)`)

**Purpose:** use Playwright to search YouTube and attempt to open/play a
matching result.

The current version uses a persistent browser profile at
`./chrome_profile`, so browser state may be retained between runs.

Keep in mind: - Browser setup, consent screens, and sign-in can affect
automation. - YouTube's page structure and selectors can change. -
Opening a video does not prove playback started. - Failures in this
experimental tool do not necessarily indicate that the other agent tools
are broken.

### 6. Human-in-the-loop approval (HITL)

**Purpose:** stop an action that needs approval before attempting it.

The current approval-gated set is:

``` python
TOOLS_REQUIRING_APPROVAL = {"delete_file"}
```

Approval state is stored in `agent_state.db`. Follow these functions:

  -------------------------------------------------------------------------------------
  Function                                          Responsibility
  ------------------------------------------------- -----------------------------------
  `init_db()`                                       Creates the approvals table if it
                                                    does not exist.

  `save_pending_approval(tool_name, arguments)`     Stores the tool, JSON arguments,
                                                    ID, and pending status.

  `create_approval_request(tool_name, arguments)`   Creates a request and displays its
                                                    ID and details.

  `decide_approval(approval_id, decision)`          Records an approved/rejected
                                                    decision for a pending request.

  `execute_approved_action(approval_id)`            Checks approval status before
                                                    handling the approved action.
  -------------------------------------------------------------------------------------

When the model requests `delete_file`, the agent creates a pending
request and pauses rather than running the action immediately.

**Important current limitations:** - `delete_file` only returns a
simulation message; it does not remove a real file. - The approval
record is persisted, but the agent does not automatically resume the
original goal after a separate decision.

### 7. Retry helper (`retry_operation(...)`)

**Purpose:** retry operations that may fail temporarily.

The helper accepts the operation to run, retryable exception types, an
optional `should_retry` predicate, and a maximum attempt count. It uses
exponential delay with jitter.

-   **Exponential backoff:** waits progressively longer between
    attempts.
-   **Jitter:** adds a random delay to reduce synchronized retries.
-   **Retry policy:** only selected failures should be retried.

Do not retry every error. Authentication problems and malformed requests
generally need correction, not another attempt. Retrying an action with
side effects may also duplicate that action.

### 8. Basic result verification (`verify_tool_result(...)`)

**Purpose:** check the returned text for obvious signs of failure.

The current helper looks for words such as `error`, `failed`,
`exception`, `timed out`, and `not found`. It also recognizes that a
simulated deletion is not a real deletion.

The verification message is sent back with the tool result so the LLM
has that context when producing its final response.

**Limitations:** this is a heuristic, not proof of success. Valid API
data could contain a phrase like "not found," and a tool can return a
success-looking message even when the intended outcome did not happen.

A stronger future design would use structured tool results, for example:

``` json
{
  "ok": true,
  "data": {},
  "error": null
}
```

Then verification can check the `ok` field and validate the expected
result for each tool.

### 9. Session memory (`messages`)

**Purpose:** keep conversation context during one running process.

The `messages` list starts with a system message. Each new user goal,
assistant response, and tool result is appended to it. This allows the
agent to refer to earlier messages in the same session.

Try:

1.  Enter: `My favorite language is Python.`
2.  Enter: `What is my favorite language?`
3.  Restart the app and ask the question again.

The first two requests should share context. After a restart, the
in-memory conversation is lost.

**Note:** SQLite currently stores approval state, not conversation
history. Persistent memory would need a separate save/load
implementation.

### 10. Planner (`create_plan(goal)`)

**Purpose:** ask the LLM to break a goal into a small number of ordered,
actionable steps.

The planner makes a separate model request with instructions to produce
a plan rather than execute it. The main loop then includes both the
original goal and the plan in the conversation.

Example goal:

``` text
Fetch a task from https://jsonplaceholder.typicode.com/todos/1,
explain the result, and calculate how many characters are in the task title.
```

A sensible plan might fetch the response, inspect the fields, explain
them, and count the characters in the title.

**Current limitation:** the plan is guidance in the conversation, not a
strict workflow engine. The LLM may combine steps, skip a step, or
answer without using a tool if it believes that is appropriate.

### 11. Tool result feedback

After Python runs a tool, the agent appends a message with
`role="tool"`, the matching `tool_call_id`, and the result. On the next
iteration, the LLM receives the result and decides whether it needs
another tool or can answer the user.

This feedback cycle is central to a tool-using agent:

``` mermaid
sequenceDiagram
    participant U as User
    participant A as Agent loop
    participant L as LLM
    participant T as Python tool
    U->>A: Goal
    A->>L: Goal + plan + tool schemas
    L-->>A: Tool call
    A->>T: Execute function
    T-->>A: Result
    A->>L: Tool result message
    L-->>A: Next tool call or final answer
    A-->>U: Final response
```

### 12. Main agent loop (`main()`)

**Purpose:** connect planning, model calls, tool execution, and
responses.

The main loop broadly follows these steps:

1.  Read a goal from the terminal.
2.  Exit if the user types `exit`.
3.  Generate and display a plan.
4.  Add the goal and plan to `messages`.
5.  Call the LLM with the available tool schemas.
6.  If the model returns no tool calls, display its answer.
7.  Otherwise parse the tool arguments and dispatch each call to the
    correct Python function.
8.  Pause tools that require approval.
9.  Handle expected errors and retries.
10. Run basic result verification.
11. Append tool results to the conversation and continue, up to the
    iteration limit.

**Debugging approach:** trace one request through this sequence: user
input → plan → LLM response → tool call → Python execution → tool result
→ final answer.

------------------------------------------------------------------------

## 🧪 Manual testing checklist

  ----------------------------------------------------------------------------------------
  Test                    Example                                  Expected check
  ----------------------- ---------------------------------------- -----------------------
  Basic calculation       `Calculate 25 * 4`                       Returns `100`.

  Division by zero        `Calculate 10 / 0`                       Controlled error; app
                                                                   remains usable.

  Successful API          Fetch `/todos/1` from JSONPlaceholder    JSON response is
                                                                   returned.

  Invalid URL             Fetch                                    Error is reported
                          `https://invalid.example.invalid/test`   without an uncaught
                                                                   crash.

  Multi-step goal         Fetch todo, explain it, count title      Uses the actual
                          characters                               returned title.

  HITL gate               `Delete test.txt`                        Approval is requested;
                                                                   no real deletion
                                                                   occurs.

  Session memory          State a preference, then ask for it      Works in the same
                                                                   process.

  Restart behavior        Restart and ask about old preference     Shows that session
                                                                   memory is temporary.

  YouTube                 Ask to play a song                       Manually verify that
                                                                   playback really starts.
  ----------------------------------------------------------------------------------------

Test failures as well as successful cases. A repeatable checklist gives
a better picture of reliability than one successful demo.

## 🔐 Security and reliability

Before using Agent Forge for real-world tasks:

-   🔑 Keep API keys in environment variables and never commit `.env`.
-   🌐 Validate and restrict URLs for API fetching.
-   🛑 Require approval for destructive or externally visible actions.
-   📂 If real file deletion is ever implemented, restrict allowed
    directories and thoroughly test the approval path.
-   🧪 Prefer structured tool outputs and verify expected outcomes.
-   🔁 Retry only transient, safe-to-retry operations.
-   ⏱️ Keep request timeouts and an agent-iteration limit.
-   🧾 Log tool names, status, duration, and safe error details; never
    log secrets.
-   🧰 Add automated tests for the calculator, retry policy, approval
    state transitions, and API tool.

Agent Forge is an educational project, not a hardened production system.

## 🗺️ Recommended next milestone

Before adding more features, test reliability with a small suite of
normal tasks, malformed tool arguments, API failures, and
approval-required actions. When behavior is stable, split `app/main.py`
into modules one responsibility at a time and rerun the tests after each
refactor.

## 📚 Glossary

  -----------------------------------------------------------------------
  Term                                Meaning
  ----------------------------------- -----------------------------------
  **LLM**                             Language model that interprets the
                                      goal and chooses a next step.

  **Tool calling**                    The model requests a specific
                                      function and provides its
                                      arguments.

  **Agent loop**                      Repeated model call → tool
                                      execution → result feedback.

  **Planner**                         Component that proposes ordered
                                      steps for a goal.

  **HITL**                            Human-in-the-loop; a person
                                      approves a gated action.

  **Backoff**                         Waiting between retry attempts,
                                      often with increasing delay.

  **Session memory**                  Context retained while the current
                                      process is running.

  **Verification**                    Checking whether a result meets
                                      basic expectations.

  **SQLite**                          A lightweight database stored in a
                                      local file.

  **Playwright**                      Library for browser automation.
  -----------------------------------------------------------------------

## 🤝 How to add a tool

1.  Implement a Python function with clear inputs and outputs.
2.  Add a matching schema to `tools`.
3.  Add dispatch logic to the main loop.
4.  Handle expected errors and set sensible timeouts.
5.  Decide whether the action needs approval.
6.  Define how success and failure are represented.
7.  Add a manual or automated test.
8.  Document the behavior and limitations here.

Keep changes small and test each tool before adding another.

------------------------------------------------------------------------

## ⚖️ Disclaimer

Agent Forge is an educational project for learning the basics of
tool-using AI agents. Review outputs and actions carefully. Do not rely
on it for sensitive, destructive, financial, or other high-impact
decisions without suitable safeguards and testing.

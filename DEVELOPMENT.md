# Development Setup

These instructions describe how to set up a development environment for the Chore Tracker web app using PyCharm.

## Prerequisites
- **Python 3.13**
- **uv** package manager ([installation instructions](https://github.com/astral-sh/uv#installation))
- **Git**
- **PyCharm**

## Initial Setup
1. Clone the repository:
   ```bash
   git clone <repo-url>
   cd choretracker
   ```
2. Install dependencies and create the virtual environment:
   ```bash
   uv sync
   ```
   This creates a `.venv` directory using Python 3.13 and installs all project dependencies.
3. Configure PyCharm to use the `uv` environment:
   1. Open **File > Settings > Python Interpreter** (macOS: **PyCharm > Settings**).
   2. Click the gear icon and choose **Add Interpreter...**, then **Add Local Interpreter**.
   3. Select **uv** on the left.
   4. If you already ran `uv sync` and see a `.venv` folder in the project root:
      - Choose **Existing environment**.
      - For **uv environment**, browse to the hidden `.venv` directory (enable *Show Hidden Files* if needed).
   5. Otherwise, let PyCharm create the env for you:
      - Choose **New environment** and set the location to the project root.
      - Ensure **Python** is set to **3.13** and click **OK**. PyCharm will run `uv sync` automatically.

## Running the Development Server
From the PyCharm terminal or a system shell, start the server with:
```bash
uv run uvicorn choretracker.app:app --host 0.0.0.0 --port 8000 --reload --reload-exclude-dir .venv
```
The application will be available at http://localhost:8000.

## Running or Debugging via PyCharm
To run or debug the server directly from PyCharm:
1. Open **Run > Edit Configurations...**
2. Click the **+** icon and choose **Python**
3. Name the configuration (e.g., `Run Server`)
4. Set **Module name** to `uvicorn`
5. In **Parameters**, enter `choretracker.app:app --host 0.0.0.0 --port 8000 --reload --reload-exclude-dir .venv`
6. Set **Working directory** to the project root
7. Ensure the Python interpreter points to the project's virtual environment (`.venv`)
8. Click **OK** to save, then use the Run or Debug button to start the server

## Stopping the Server
Press `Ctrl+C` in the terminal where the server is running.

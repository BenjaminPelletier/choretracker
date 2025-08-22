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
3. In PyCharm, select **Add Interpreter** and point it to the `.venv/bin/python` (macOS/Linux) or `.venv\Scripts\python.exe` (Windows) inside the project directory.

## Running the Development Server
From the PyCharm terminal or a system shell, start the server with:
```bash
uv run uvicorn choretracker.app:app --reload
```
The application will be available at http://localhost:8000.

## Running or Debugging via PyCharm
To run or debug the server directly from PyCharm:
1. Open **Run > Edit Configurations...**
2. Click the **+** icon and choose **Python**
3. Name the configuration (e.g., `Run Server`)
4. Set **Module name** to `uvicorn`
5. In **Parameters**, enter `choretracker.app:app --reload`
6. Set **Working directory** to the project root
7. Ensure the Python interpreter points to the project's virtual environment (`.venv`)
8. Click **OK** to save, then use the Run or Debug button to start the server

## Stopping the Server
Press `Ctrl+C` in the terminal where the server is running.

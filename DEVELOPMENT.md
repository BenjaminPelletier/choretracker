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
uv run uvicorn choretracker.app:app --host 0.0.0.0 --port 8000 --reload --reload-exclude .venv
```
The application will be available at http://localhost:8000.

## Running or Debugging via PyCharm
To run or debug the server directly from PyCharm:
1. Open **Run > Edit Configurations...**
2. Click the **+** icon and choose **Python**
3. Name the configuration (e.g., `Run Server`)
4. Set **Module name** to `uvicorn`
5. In **Parameters**, enter `choretracker.app:app --host 0.0.0.0 --port 8000 --reload --reload-exclude .venv`
6. Set **Working directory** to the project root
7. Ensure the Python interpreter points to the project's virtual environment (`.venv`)
8. Click **OK** to save, then use the Run or Debug button to start the server

## Stopping the Server
Press `Ctrl+C` in the terminal where the server is running.

## Database Layout
The application uses a SQLite database via SQLModel. Three tables are
defined:

- **User** – stores authentication credentials, permissions and optional
  profile pictures.
- **CalendarEntry** – holds events, chores and reminders along with
  recurrence information.
- **ChoreCompletion** – records completed chore instances. Each record
  references a calendar entry and is automatically removed if its parent
  entry is deleted.

Foreign key constraints are enabled on startup to maintain referential
integrity.

## Database Migrations

Schema changes are managed with [Alembic](https://alembic.sqlalchemy.org/).
When you modify any of the SQLModel table definitions, create and apply a
migration:

1. Generate a migration script after editing the models:

   ```bash
   uv run alembic revision --autogenerate -m "describe change"
   ```

2. Apply the migration to your local database:

   ```bash
   uv run alembic upgrade head
   ```

3. Commit the generated file under `migrations/versions` along with your
   code changes.

New installations can be initialized by running `alembic upgrade head` or by
starting the application, which will create the initial schema automatically.

## Building the image from a dev machine

Although the GitHub Action should build and upload a Docker image upon releases, to manually build and upload a Docker image:

* `docker buildx create --use --name choretracker-builder`
* `docker buildx inspect --bootstrap`
* `docker login`
* `docker buildx build --platform linux/arm/v7 --build-arg CHORETRACKER_VERSION=dev -t benpelletier/choretracker:dev --push .`

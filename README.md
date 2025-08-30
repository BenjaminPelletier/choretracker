# choretracker

## Execution

The application stores information in a SQLite database. By default, the database
file `choretracker.db` is created in the working directory. To use a different
location, set the `CHORETRACKER_DB` environment variable to the desired path.

The server also requires a secret key for session management. Before starting
the application, set `CHORETRACKER_SECRET_KEY` to a secure, random value and
keep it consistent between restarts.

Time-based operations use the `CHORETRACKER_TZ` environment variable to set
the application's timezone. If unspecified, the default timezone is the
system's timezone. For example, to run the application in Los Angeles time,
set `CHORETRACKER_TZ=America/Los_Angeles`.

If no existing user has the `admin` permission, a new database is automatically
populated with an `Admin` user (password `admin`, PIN `0000`) that has the
`admin` permission. The `admin` permission grants all actions, including those
normally requiring `iam`.

### Direct execution

```bash
CHORETRACKER_DB=/path/to/choretracker.db \
CHORETRACKER_SECRET_KEY=$(openssl rand -hex 32) \
uv run uvicorn choretracker.app:app --host 0.0.0.0 --port 8000 --reload --reload-exclude .venv
```

### Docker

When running in Docker, pass the environment variables and mount a volume for
the database file:

```bash
docker run -e CHORETRACKER_DB=/data/choretracker.db \
  -e CHORETRACKER_SECRET_KEY=$(openssl rand -hex 32) \
  -v $(pwd)/data:/data -p 8000:8000 benpelletier/choretracker
```

_Note that older versions of Docker may require the use of `--security-opt seccomp=unconfined` to support the `clone3` system the Tokio runtime uses._

## Database migrations

Schema changes between releases are handled with Alembic migrations. When
upgrading to a new version that includes migrations, apply them before
starting the server:

```bash
uv run alembic upgrade head
```

Ensure the `CHORETRACKER_DB` environment variable points at the same database
file that the application will use. When running in Docker, execute the
migration inside the container, for example:

```bash
docker run --rm -e CHORETRACKER_DB=/data/choretracker.db \
  -v $(pwd)/data:/data benpelletier/choretracker \
  uv run alembic upgrade head
```

_Note that older versions of Docker may require the use of `--security-opt seccomp=unconfined` to support the `clone3` system the Tokio runtime uses._

No further action is required; the application will operate with the updated
schema once the migration completes.

The server verifies the database's Alembic revision on startup and will exit
with an error if the schema is not up to date.

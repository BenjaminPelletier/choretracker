# choretracker

## Docker

The app can run inside Docker containers.

### Quick start

- **Start the webserver** (uses existing image):
  ```bash
  make docker-start
  ```
- **Stop the containers**:
  ```bash
  make docker-stop
  ```
- **Rebuild the webserver image and restart**:
  ```bash
  make docker-rebuild
  ```

The webserver listens on [http://localhost:8000](http://localhost:8000).

## Database configuration

The application stores users in a SQLite database. By default, the database
file `choretracker.db` is created in the working directory. To use a different
location, set the `CHORETRACKER_DB` environment variable to the desired path.

### Direct execution

```bash
CHORETRACKER_DB=/path/to/choretracker.db uv run uvicorn choretracker.app:app --reload
```

### Docker

When running in Docker, pass the environment variable and mount a volume for
the database file:

```bash
docker run -e CHORETRACKER_DB=/data/choretracker.db -v $(pwd)/data:/data -p 8000:8000 benpelletier/choretracker_webserver
```

A new database is automatically populated with an `Admin` user (password
`admin`, PIN `0000`) that has both `admin` and `iam` permissions.

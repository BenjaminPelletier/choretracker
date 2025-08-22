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

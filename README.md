# HomeGame

## Prerequisites

- Docker Engine with the Docker Compose plugin
- A configured `.env` file in the repository root

Use `.env.example` as a reference when configuring `.env`. Set the variables required by `docker-compose.yml` before running any Compose commands. Keep `.env` private and do not commit it.

## Usage

From the repository root:

```sh
make up       # Build and start db, backend, and frontend in the background
make migrate  # Apply Django migrations in the running backend container
make test     # Run Django tests in the running backend container
```

The backend startup command already applies migrations before starting Daphne. Run `make migrate` to apply migrations explicitly; `make migrate` and `make test` require the backend container to be running.

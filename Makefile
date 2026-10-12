.PHONY: up migrate test stop

# `-T` disables TTY allocation for the `exec` commands below. Without it,
# non-interactive callers (CI, agents, redirected output) get no command output
# and a misleading exit status, which silently turns this file into a false gate.

up:
	docker compose up -d --build

migrate:
	docker compose exec -T backend python manage.py migrate

test:
	docker compose exec -T backend python manage.py test tests

stop:
	docker compose stop

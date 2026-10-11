.PHONY: up migrate test stop

up:
	docker compose up -d --build

migrate:
	docker compose exec backend python manage.py migrate

test:
	docker compose exec backend python manage.py test tests

stop:
	docker compose stop

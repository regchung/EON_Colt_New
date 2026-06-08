.PHONY: up down build logs migrate revision psql restart

up:
	docker compose up --build -d

build:
	docker compose build

down:
	docker compose down

restart:
	docker compose restart backend

logs:
	docker compose logs -f

migrate:
	docker compose exec backend alembic upgrade head

revision:
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

psql:
	docker compose exec db psql -U smartcar -d smartcar

osrm-prepare:
	./osrm/prepare.sh

osrm-up:
	docker compose --profile osrm up -d osrm

osrm-down:
	docker compose --profile osrm stop osrm

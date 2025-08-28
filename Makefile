.PHONY: docker-start docker-stop docker-rebuild test

docker-start:
	docker compose up --no-build -d

docker-stop:
	docker compose down

docker-rebuild:
	docker compose build web
	docker compose up -d

test:
	./scripts/test.sh

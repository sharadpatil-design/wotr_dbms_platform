.PHONY: build up down logs ingest run-etl

build:
	docker-compose build

up:
	docker-compose up -d
	powershell -Command "Start-Sleep -Seconds 5"


down:
	docker-compose down --volumes

logs:
	docker-compose logs -f

ingest:
	python3 tools/ingest_test.py

run-etl:
	docker-compose run --rm spark-job

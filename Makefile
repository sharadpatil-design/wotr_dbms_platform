.PHONY: build up down logs ingest run-etl backup restore retention-cleanup start-backup-scheduler start-retention-scheduler stop-schedulers

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

# Backup and retention commands
backup:
	docker-compose -f docker-compose.backup.yml run --rm backup-scheduler /scripts/backup.sh

restore:
	@echo "Usage: make restore BACKUP_DIR=/backups/YYYYMMDD_HHMMSS"
	@docker-compose -f docker-compose.backup.yml run --rm backup-scheduler ls -lt /backups/

retention-cleanup:
	docker exec fastapi python /app/retention_cleanup.py

start-backup-scheduler:
	docker-compose -f docker-compose.backup.yml up -d

start-retention-scheduler:
	docker-compose -f docker-compose.retention.yml up -d

stop-schedulers:
	docker-compose -f docker-compose.backup.yml down
	docker-compose -f docker-compose.retention.yml down

# Testing commands
.PHONY: test test-unit test-integration test-load benchmark install-test-deps

install-test-deps:
	pip install -r tests/requirements.txt

test-unit:
	pytest services/api/tests/ -v

test-unit-cov:
	pytest services/api/tests/ -v --cov=services/api/app --cov-report=html --cov-report=term

test-integration:
	pytest tests/integration/ -v -s -m integration

test: test-unit

benchmark:
	python tests/benchmark/benchmark.py

test-load:
	@echo "Starting Locust load test..."
	@echo "Access web UI at http://localhost:8089"
	locust -f tests/load/load_test.py --host http://localhost:8000

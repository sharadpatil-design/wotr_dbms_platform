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

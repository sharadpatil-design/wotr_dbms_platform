#!/bin/bash
set -e
export AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-minioadmin}
export AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-minioadmin}
export MINIO_ENDPOINT=${MINIO_ENDPOINT:-minio:9000}
python3 etl_job.py

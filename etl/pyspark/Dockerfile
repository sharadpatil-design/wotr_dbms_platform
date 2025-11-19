FROM eclipse-temurin:11-jre-jammy
RUN apt-get update && apt-get install -y python3 python3-pip curl && rm -rf /var/lib/apt/lists/*
RUN pip3 install pyspark==3.4.1 boto3 s3fs pandas
WORKDIR /app
COPY . /app
ENTRYPOINT ["/bin/bash", "-c", "/app/run_job.sh"]

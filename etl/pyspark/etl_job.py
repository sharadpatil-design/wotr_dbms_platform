from pyspark.sql import SparkSession
from pyspark.sql.functions import lit
import os, sys

MINIO = os.getenv("MINIO_ENDPOINT", "minio:9000")
BUCKET = os.getenv("MINIO_BUCKET", "raw-data")
s3_endpoint = f"http://{MINIO}"

spark = SparkSession.builder     .appName("wotr-etl")     .config("spark.hadoop.fs.s3a.endpoint", s3_endpoint)     .config("spark.hadoop.fs.s3a.access.key", os.getenv("AWS_ACCESS_KEY_ID", "minioadmin"))     .config("spark.hadoop.fs.s3a.secret.key", os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin"))     .config("spark.hadoop.fs.s3a.path.style.access", "true")     .getOrCreate()

raw_path = f"s3a://{BUCKET}/raw/"
curated_path = f"s3a://{BUCKET}/curated/"

try:
    df = spark.read.json(raw_path)
except Exception as e:
    print("No data to process:", e)
    spark.stop(); sys.exit(0)

df2 = df.withColumn("processed_flag", lit("Y"))
df2.write.mode("append").parquet(curated_path)
print("Wrote curated parquet to", curated_path)
spark.stop()

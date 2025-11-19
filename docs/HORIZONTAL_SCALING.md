# WOTR Platform - Horizontal Scaling Configuration

## Overview
This document describes horizontal scaling strategies for the WOTR platform to handle increased load and ensure high availability.

## Scaling Strategies

### 1. FastAPI Service Scaling

**Docker Compose (Development/Testing)**

Scale FastAPI instances:
```bash
docker-compose up -d --scale fastapi=3
```

**Production Kubernetes**

```yaml
# k8s/fastapi-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wotr-api
  namespace: wotr
spec:
  replicas: 3
  selector:
    matchLabels:
      app: wotr-api
  template:
    metadata:
      labels:
        app: wotr-api
    spec:
      containers:
      - name: fastapi
        image: wotr/fastapi:latest
        ports:
        - containerPort: 8000
        env:
        - name: POSTGRES_HOST
          value: "postgres-service"
        - name: REDIS_HOST
          value: "redis-service"
        - name: KAFKA_BOOTSTRAP
          value: "kafka-service:9092"
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: wotr-api-service
  namespace: wotr
spec:
  selector:
    app: wotr-api
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

**Horizontal Pod Autoscaler (HPA)**

```yaml
# k8s/fastapi-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: wotr-api-hpa
  namespace: wotr
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: wotr-api
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: "1000"
```

### 2. Consumer Service Scaling

**Docker Compose**

Scale consumers for parallel processing:
```bash
docker-compose up -d --scale consumer=5
```

**Kubernetes**

```yaml
# k8s/consumer-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wotr-consumer
  namespace: wotr
spec:
  replicas: 5
  selector:
    matchLabels:
      app: wotr-consumer
  template:
    metadata:
      labels:
        app: wotr-consumer
    spec:
      containers:
      - name: consumer
        image: wotr/consumer:latest
        env:
        - name: KAFKA_BOOTSTRAP
          value: "kafka-service:9092"
        - name: KAFKA_GROUP_ID
          value: "wotr-consumer-group"
        - name: CLICKHOUSE_HOST
          value: "clickhouse-service"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

**Key Configuration for Consumer Scaling:**

- Use same `KAFKA_GROUP_ID` for all consumer instances
- Kafka will automatically distribute partitions among consumers
- Number of consumers should not exceed number of topic partitions

### 3. Load Balancing

**Nginx Configuration (Production)**

```nginx
# nginx/wotr-loadbalancer.conf
upstream wotr_api {
    least_conn;  # Use least connections algorithm
    server fastapi-1:8000 max_fails=3 fail_timeout=30s;
    server fastapi-2:8000 max_fails=3 fail_timeout=30s;
    server fastapi-3:8000 max_fails=3 fail_timeout=30s;
    
    # Health check
    check interval=3000 rise=2 fall=3 timeout=1000 type=http;
    check_http_send "GET /health HTTP/1.0\r\n\r\n";
    check_http_expect_alive http_2xx http_3xx;
}

server {
    listen 80;
    server_name api.wotr.com;
    
    location / {
        proxy_pass http://wotr_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Request-ID $request_id;
        
        # Timeouts
        proxy_connect_timeout 10s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
        
        # Connection pooling
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
    
    location /metrics {
        # Restrict metrics access
        allow 10.0.0.0/8;
        deny all;
        proxy_pass http://wotr_api;
    }
}
```

**HAProxy Configuration (Alternative)**

```haproxy
# haproxy/wotr.cfg
global
    log /dev/log local0
    maxconn 4096
    
defaults
    log global
    mode http
    option httplog
    option dontlognull
    timeout connect 10s
    timeout client 30s
    timeout server 30s
    
frontend wotr_api_frontend
    bind *:80
    default_backend wotr_api_backend
    
backend wotr_api_backend
    balance roundrobin
    option httpchk GET /health
    http-check expect status 200
    
    server fastapi1 fastapi-1:8000 check inter 5s fall 3 rise 2
    server fastapi2 fastapi-2:8000 check inter 5s fall 3 rise 2
    server fastapi3 fastapi-3:8000 check inter 5s fall 3 rise 2
```

### 4. Database Scaling

**PostgreSQL Replication**

```yaml
# k8s/postgres-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: wotr
spec:
  serviceName: postgres
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:15
        env:
        - name: POSTGRES_REPLICATION_MODE
          value: "master"
        - name: POSTGRES_REPLICATION_USER
          value: "replicator"
        volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: postgres-data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      resources:
        requests:
          storage: 50Gi
```

**ClickHouse Cluster**

```xml
<!-- clickhouse/config.d/cluster.xml -->
<clickhouse>
    <remote_servers>
        <wotr_cluster>
            <shard>
                <replica>
                    <host>clickhouse-1</host>
                    <port>9000</port>
                </replica>
                <replica>
                    <host>clickhouse-2</host>
                    <port>9000</port>
                </replica>
            </shard>
            <shard>
                <replica>
                    <host>clickhouse-3</host>
                    <port>9000</port>
                </replica>
                <replica>
                    <host>clickhouse-4</host>
                    <port>9000</port>
                </replica>
            </shard>
        </wotr_cluster>
    </remote_servers>
    
    <zookeeper>
        <node>
            <host>zookeeper-1</host>
            <port>2181</port>
        </node>
        <node>
            <host>zookeeper-2</host>
            <port>2181</port>
        </node>
        <node>
            <host>zookeeper-3</host>
            <port>2181</port>
        </node>
    </zookeeper>
</clickhouse>
```

**Redis Cluster**

```yaml
# k8s/redis-cluster.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-cluster
  namespace: wotr
spec:
  serviceName: redis-cluster
  replicas: 6
  selector:
    matchLabels:
      app: redis-cluster
  template:
    metadata:
      labels:
        app: redis-cluster
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        command:
        - redis-server
        - /conf/redis.conf
        - --cluster-enabled yes
        - --cluster-config-file /data/nodes.conf
        - --cluster-node-timeout 5000
        - --appendonly yes
        ports:
        - containerPort: 6379
          name: client
        - containerPort: 16379
          name: gossip
        volumeMounts:
        - name: conf
          mountPath: /conf
        - name: data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      resources:
        requests:
          storage: 10Gi
```

### 5. Kafka/Redpanda Scaling

**Increase Partitions**

```bash
# Create topic with more partitions
rpk topic create ingest-events --partitions 10 --replicas 3

# Or alter existing topic
rpk topic alter-config ingest-events --set partition-count=10
```

**Kafka Cluster (Kubernetes)**

```yaml
# k8s/kafka-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: kafka
  namespace: wotr
spec:
  serviceName: kafka
  replicas: 3
  selector:
    matchLabels:
      app: kafka
  template:
    metadata:
      labels:
        app: kafka
    spec:
      containers:
      - name: kafka
        image: confluentinc/cp-kafka:latest
        env:
        - name: KAFKA_BROKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: KAFKA_ZOOKEEPER_CONNECT
          value: "zookeeper:2181"
        - name: KAFKA_ADVERTISED_LISTENERS
          value: "PLAINTEXT://$(POD_IP):9092"
        ports:
        - containerPort: 9092
```

## Performance Tuning

### Connection Pool Settings

**Optimal Pool Sizes (per instance):**

- **PostgreSQL Pool**: min=2, max=10
- **ClickHouse Pool**: 10 connections
- **Kafka Producer Pool**: 5 producers
- **Redis Pool**: 50 connections

**For scaled deployments:**
- Total connections = pool_size × number_of_instances
- Ensure database max_connections > total_connections

### Resource Allocation

**Per FastAPI Instance:**
- CPU: 500m - 1000m
- Memory: 512Mi - 1Gi

**Per Consumer Instance:**
- CPU: 250m - 500m
- Memory: 256Mi - 512Mi

### Partition Strategy

**Kafka Topics:**
- `ingest-events`: 10 partitions (matches consumer scale)
- `dlq-events`: 3 partitions
- Partition key: event source or event type

**ClickHouse:**
- Partition by: `toYYYYMM(created_at)`
- Shard by: `cityHash64(id)`

## Monitoring Scaled Deployments

**Key Metrics:**

1. **Per-Instance Metrics:**
   - CPU/Memory usage
   - Request rate
   - Error rate
   - Connection pool utilization

2. **Cluster Metrics:**
   - Total throughput
   - Load distribution
   - Replication lag
   - Consumer lag

3. **Prometheus Queries:**

```promql
# Average latency across all instances
avg(rate(fastapi_request_duration_seconds_sum[5m]) / rate(fastapi_request_duration_seconds_count[5m])) by (instance)

# Request rate per instance
sum(rate(fastapi_requests_total[5m])) by (instance)

# Connection pool utilization
(postgres_pool_size - postgres_pool_available) / postgres_pool_size

# Consumer lag
sum(kafka_consumer_lag) by (consumer_group, partition)
```

## Deployment Checklist

### Before Scaling

- [ ] Verify health checks are configured
- [ ] Ensure connection pools are properly sized
- [ ] Configure session affinity (if needed)
- [ ] Set up monitoring for new instances
- [ ] Test load balancer configuration
- [ ] Verify database connection limits
- [ ] Check Kafka partition count

### After Scaling

- [ ] Verify all instances are healthy
- [ ] Check load distribution across instances
- [ ] Monitor resource utilization
- [ ] Verify consumer group rebalancing
- [ ] Test failover scenarios
- [ ] Check replication lag
- [ ] Validate metrics collection

## Cost Optimization

**Auto-scaling Configuration:**

```yaml
# Scale down during off-peak hours
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: wotr-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: wotr-api
  minReplicas: 2  # Off-peak
  maxReplicas: 10  # Peak
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Pods
        value: 2
        periodSeconds: 60
```

## Disaster Recovery

**Multi-Region Deployment:**

1. Primary region: All services active
2. Secondary region: Read replicas + standby services
3. Failover: Promote secondary to primary
4. Data replication: PostgreSQL streaming replication, ClickHouse distributed tables

**Backup Strategy:**

- PostgreSQL: WAL archiving + daily snapshots
- ClickHouse: Daily backups to S3
- Redis: AOF persistence + snapshots
- MinIO: Cross-region replication

## Troubleshooting Scaled Deployments

**Uneven Load Distribution:**
- Check load balancer algorithm (use least_conn)
- Verify all instances are healthy
- Check connection pooling settings

**Consumer Rebalancing Issues:**
- Ensure consumer group ID is consistent
- Check Kafka partition count vs consumer count
- Verify session timeout settings

**Connection Pool Exhaustion:**
- Increase pool size
- Check for connection leaks
- Monitor connection duration

**High Inter-Service Latency:**
- Use service mesh (Istio/Linkerd)
- Implement circuit breakers
- Add retries with exponential backoff

---

**Last Updated:** 2025-11-19  
**Review Schedule:** Quarterly  
**Owner:** Platform Team

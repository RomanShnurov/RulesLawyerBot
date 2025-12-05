# Docker Quick Reference for RulesLawyerBot

Quick guide for common Docker operations and troubleshooting.

## Building and Running

### Build Image

```bash
# Basic build
docker build -t ruleslawyerbot:latest .

# Build with BuildKit caching
docker build -t ruleslawyerbot:latest \
  --cache-from=type=registry \
  --cache-to=type=registry,ref=registry.example.com/ruleslawyerbot \
  .

# Check image size
docker images ruleslawyerbot
```

### Run Container

```bash
# Using docker-compose (recommended)
docker-compose up -d

# Using docker run
docker run -d \
  --name boardgame-bot \
  --restart unless-stopped \
  -e TELEGRAM_TOKEN=$TELEGRAM_TOKEN \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -v $(pwd)/rules_pdfs:/app/rules_pdfs \
  -v $(pwd)/data:/app/data \
  ruleslawyerbot:latest
```

## Debugging

### View Logs

```bash
# Using docker-compose
docker-compose logs -f app

# Using docker
docker logs -f boardgame-bot

# View last 100 lines
docker-compose logs --tail=100 app

# View logs since specific time
docker logs --since 2025-12-06T10:00:00 boardgame-bot
```

### Health Status

```bash
# Check container health
docker ps --no-trunc | grep boardgame-bot

# Expected output shows: (healthy) or (unhealthy)

# Check health status details
docker inspect --format='{{json .State.Health}}' boardgame-bot | jq

# Run health check manually
docker exec boardgame-bot python -m src.health readiness
```

### Container Shell

```bash
# Get shell access (if available)
docker exec -it boardgame-bot /bin/bash

# Note: The current container uses non-root user
# If you need root for debugging:
docker run -it --rm \
  -v $(pwd)/rules_pdfs:/app/rules_pdfs \
  -v $(pwd)/data:/app/data \
  --user root \
  ruleslawyerbot:latest /bin/bash
```

### Inspect Container

```bash
# View container configuration
docker inspect boardgame-bot

# View environment variables
docker inspect --format='{{json .Config.Env}}' boardgame-bot | jq

# View volumes
docker inspect --format='{{json .Mounts}}' boardgame-bot | jq

# View network configuration
docker inspect --format='{{json .NetworkSettings}}' boardgame-bot | jq
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs app

# Common issues:
# 1. Missing environment variables
# 2. Volume permission issues
# 3. Port already in use
# 4. Insufficient memory
```

### Health Check Failing

```bash
# Run health check script directly
docker exec boardgame-bot python -m src.health readiness

# Check startup check
docker exec boardgame-bot python -m src.health startup

# Check liveness
docker exec boardgame-bot python -m src.health liveness
```

### Volume Permission Issues

```bash
# Fix volume ownership
sudo chown -R 1000:1000 ./rules_pdfs ./data

# Make volumes writable
chmod 700 ./rules_pdfs ./data

# Check permissions
ls -la rules_pdfs/ data/
```

### High Memory Usage

```bash
# Check memory consumption
docker stats boardgame-bot

# View container memory limit
docker inspect --format='{{.HostConfig.Memory}}' boardgame-bot

# Calculate from bytes: 1073741824 = 1GB
```

### Network Issues

```bash
# Check container network
docker inspect --format='{{json .NetworkSettings}}' boardgame-bot | jq

# Test connectivity from container
docker exec boardgame-bot curl -v https://api.openai.com

# Check DNS resolution
docker exec boardgame-bot nslookup api.openai.com
```

## Maintenance

### Clean Up

```bash
# Remove stopped containers
docker container prune

# Remove unused images
docker image prune

# Remove everything unused
docker system prune -a

# View disk usage
docker system df
```

### Update Image

```bash
# Rebuild image
docker-compose build

# Update and restart
docker-compose up --build -d

# Verify new image is running
docker ps --no-trunc | grep boardgame-bot
```

### Backup Data

```bash
# Backup database and PDFs
tar -czf backup-$(date +%Y%m%d).tar.gz data/ rules_pdfs/

# Restore from backup
tar -xzf backup-20251206.tar.gz
```

## Performance

### Check Resource Usage

```bash
# Real-time stats
docker stats boardgame-bot

# Historical stats (if using json-file logging)
docker logs --tail=100 boardgame-bot | grep -i "memory\|cpu"
```

### Optimize Image Size

```bash
# Check layer sizes
docker history ruleslawyerbot:latest

# Analyze image content
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  wagoodman/dive:latest ruleslawyerbot:latest
```

### Monitor Over Time

```bash
# Export container stats to file
docker stats --no-stream --format "{{.Container}},{{.CPUPerc}},{{.MemUsage}}" \
  > stats.csv

# Watch for memory leaks
watch -n 5 'docker stats --no-stream boardgame-bot'
```

## Advanced

### Multi-Stage Build Verification

```bash
# Check intermediate stages
docker build --target builder -t ruleslawyerbot:builder .

# Inspect builder stage
docker run -it ruleslawyerbot:builder ls -la /build/.venv/lib
```

### Security Scanning

```bash
# Scan with Trivy
trivy image ruleslawyerbot:latest

# Export scan results
trivy image -f json -o scan-results.json ruleslawyerbot:latest

# Check specific severity
trivy image --severity HIGH,CRITICAL ruleslawyerbot:latest
```

### Push to Registry

```bash
# Tag image
docker tag ruleslawyerbot:latest registry.example.com/ruleslawyerbot:latest

# Push
docker push registry.example.com/ruleslawyerbot:latest

# Push with BuildKit inline caching
docker buildx build --push \
  --cache-to type=inline \
  -t registry.example.com/ruleslawyerbot:latest \
  .
```

## Environment Setup

### Create .env File

```bash
cat > .env << EOF
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1
OPENAI_MODEL=gpt-5-nano
LOG_LEVEL=INFO
MAX_REQUESTS_PER_MINUTE=10
MAX_CONCURRENT_SEARCHES=4
EOF
```

### Verify Environment

```bash
# Check env file is valid
grep -E "^[A-Z_]+=.*" .env | wc -l

# Load and verify
set -o allexport
source .env
set +o allexport

echo "TELEGRAM_TOKEN set: ${TELEGRAM_TOKEN:0:10}..."
```

## Common Commands Reference

| Task | Command |
|------|---------|
| Start bot | `docker-compose up -d` |
| Stop bot | `docker-compose down` |
| View logs | `docker-compose logs -f app` |
| Restart | `docker-compose restart app` |
| Rebuild | `docker-compose build` |
| Check health | `docker ps \| grep boardgame-bot` |
| Shell access | `docker exec -it boardgame-bot bash` |
| View config | `docker inspect boardgame-bot` |
| Clean up | `docker system prune` |
| Update | `docker-compose pull && docker-compose up -d` |

## Helpful Scripts

### Health Check Script

```bash
#!/bin/bash
# scripts/check-health.sh

echo "Checking RulesLawyerBot health..."

# Container running?
if ! docker ps --filter name=boardgame-bot --quiet | grep -q .; then
    echo "ERROR: Container not running"
    exit 1
fi

# Health check
HEALTH=$(docker inspect --format='{{json .State.Health.Status}}' boardgame-bot)
echo "Health status: $HEALTH"

if [ "$HEALTH" = '"healthy"' ]; then
    echo "Bot is healthy"
    exit 0
else
    echo "ERROR: Bot is not healthy"
    docker-compose logs --tail=20 app
    exit 1
fi
```

### Backup Script

```bash
#!/bin/bash
# scripts/backup.sh

BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

echo "Backing up RulesLawyerBot data..."

tar -czf "$BACKUP_DIR/backup_$TIMESTAMP.tar.gz" \
    data/ \
    rules_pdfs/ \
    .env

echo "Backup created: $BACKUP_DIR/backup_$TIMESTAMP.tar.gz"

# Keep only last 7 backups
find "$BACKUP_DIR" -name "backup_*.tar.gz" -mtime +7 -delete
```

### Update Script

```bash
#!/bin/bash
# scripts/update.sh

echo "Updating RulesLawyerBot..."

# Stop current instance
docker-compose down

# Rebuild image
docker-compose build

# Start new instance
docker-compose up -d

# Wait for health check
echo "Waiting for bot to become healthy..."
for i in {1..30}; do
    if docker exec boardgame-bot python -m src.health readiness > /dev/null 2>&1; then
        echo "Bot is healthy!"
        exit 0
    fi
    echo "Waiting... ($i/30)"
    sleep 1
done

echo "ERROR: Bot failed to become healthy"
docker-compose logs app
exit 1
```

## Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Security Best Practices](https://docs.docker.com/engine/security/)

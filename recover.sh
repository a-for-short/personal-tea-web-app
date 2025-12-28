#!/bin/bash
set -e

echo "🔄 Recovering Tea Tracker..."

# Stop and clean
echo "Cleaning up..."
sudo docker compose down -v 2>/dev/null || true
docker rm -f tea-app 2>/dev/null || true
docker volume rm tea_data 2>/dev/null || true

# Reset directories
echo "Resetting directories..."
rm -rf data logs
mkdir -p data logs
chmod 755 data logs

# Create minimal docker-compose.yml
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  tea:
    build: .
    container_name: tea-app
    restart: unless-stopped
    volumes:
      - ./data:/app/data
    ports:
      - "127.0.0.1:5000:5000"
    environment:
      - FLASK_DEBUG=0
      - PORT=5000
      - SECRET_KEY=${SECRET_KEY:-default-secret-change-me}
EOF

# Create minimal Dockerfile
cat > Dockerfile << 'EOF'
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directory
RUN mkdir -p /app/data

# Use non-root user
RUN useradd -r -u 1000 appuser
USER appuser

CMD ["gunicorn", "-w", "3", "-b", "0.0.0.0:5000", "app:app"]
EOF

# Fix app.py logging (simple fix - remove file logging)
echo "Fixing app.py logging..."
if grep -q "setup_logging" app.py; then
    # Remove the setup_logging function
    sed -i '/def setup_logging/,/^def / { /def setup_logging/,/setup_logging()/d }' app.py
    # Add simple logging config
    sed -i '1a import logging\nlogging.basicConfig(level=logging.INFO)' app.py
fi

# Create .env if missing
if [ ! -f .env ]; then
    echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > .env
fi

# Build and run
echo "Building and starting..."
sudo docker compose build --no-cache
sudo docker compose up -d

sleep 3

echo ""
echo "📋 Status:"
docker ps | grep tea || echo "Container not running"

echo ""
echo "📝 Logs:"
docker logs tea-app --tail 10 2>&1 || echo "Cannot get logs"

echo ""
echo "✅ Recovery complete!"
echo "🔗 Visit: http://localhost:5000"
echo "📊 Check data: ls -la data/"
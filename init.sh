#!/bin/bash
set -e

echo "🔧 Setting up Tea Tracker..."

# Create directories
mkdir -p data logs

# Set proper ownership to your user (not root!)
sudo chown -R $(id -u):$(id -g) data logs
chmod 755 data logs

# Create .env if missing
if [ ! -f .env ]; then
    echo "Generating .env file..."
    echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > .env
    echo "Created .env with random SECRET_KEY"
fi

echo "📦 Building Docker image..."
sudo docker compose build

echo "🚀 Starting application..."
sudo docker compose up -d

echo ""
echo "✅ Setup complete!"
echo "🔗 Admin: http://localhost:5000"
echo "🍵 Brew: http://localhost:5000/brew"
echo ""
echo "📊 Database location: ./data/tea.db"
echo "📝 Logs: ./data/logs/"
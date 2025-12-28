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

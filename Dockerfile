FROM python:3.11-slim

# Environment
ENV PYTHONUNBUFFERED=1 \
    PRETIX_CONFIG_FILE=/etc/pretix/pretix.cfg \
    PRETIX_DATA_DIR=/data \
    PATH="/opt/pretix/.local/bin:$PATH"

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential libpq-dev libjpeg-dev zlib1g-dev gettext \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /opt/pretix

# Copy the entire Pretix instance source code into the Docker image
COPY . /opt/pretix/

# Install Pretix dependencies (including the plugins from the copied source)
RUN pip install --upgrade pip \
    && pip install gunicorn
RUN pip install --no-cache-dir -e .

# Create Pretix config directory
RUN mkdir -p /etc/pretix /data /var/log/pretix

# Copy a sample config file if you want later
COPY pretix.cfg /etc/pretix/pretix.cfg

# Collect static files and migrate database
# RUN python src/manage.py migrate --noinput
RUN python src/manage.py rebuild --noinput

# Expose HTTP port
EXPOSE 8000

# Start Pretix web
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "src.pretix.wsgi"]

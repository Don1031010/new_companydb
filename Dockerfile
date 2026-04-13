# Use an official Python runtime based on Debian 12 "bookworm" as a parent image.
FROM python:3.12-slim-bookworm

# Add user that will be used in the container.
RUN useradd --create-home --uid 1002 wagtail

# Port used by this container to serve HTTP.
EXPOSE 8000

# Set environment variables.
# 1. Force Python stdout and stderr streams to be unbuffered.
# 2. Set PORT variable that is used by Gunicorn. This should match "EXPOSE" command.
# 3. Default Django settings module (can be overridden via .env or docker-compose).
# 4. Playwright browser path (only used in scraper image).
ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DJANGO_SETTINGS_MODULE=mysite.settings.dev \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install runtime system packages required by Wagtail/Pillow.
# build-essential is installed temporarily below and then purged to keep image lean.
RUN apt-get update --yes --quiet && apt-get install --yes --quiet --no-install-recommends \
    libjpeg62-turbo \
    zlib1g \
    libwebp7 \
 && rm -rf /var/lib/apt/lists/*

# Install Python packages:
#   - Install build deps temporarily, build wheels, then purge them.
#   - This keeps the final image free of gcc/headers (~200 MB savings).
COPY requirements.txt /
RUN apt-get update --yes --quiet && \
    apt-get install --yes --quiet --no-install-recommends \
        build-essential \
        libjpeg62-turbo-dev \
        zlib1g-dev \
        libwebp-dev \
    && pip install --no-cache-dir -r /requirements.txt \
    && apt-get purge --yes build-essential libjpeg62-turbo-dev zlib1g-dev libwebp-dev \
    && apt-get autoremove --yes \
    && rm -rf /var/lib/apt/lists/*

# ── Playwright / Chromium (scraper image only) ────────────────────────────────
# Build normally for web. Pass --build-arg INSTALL_PLAYWRIGHT=true for scraper.
ARG INSTALL_PLAYWRIGHT=false
RUN if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then \
        pip install --no-cache-dir playwright && \
        playwright install --with-deps chromium && \
        apt-get update --quiet && \
        apt-get install -y --no-install-recommends xvfb && \
        rm -rf /var/lib/apt/lists/*; \
    fi

# Use /app folder as a directory where the source code is stored.
WORKDIR /app

# Create media and static directories for user-uploaded files and collected assets.
RUN mkdir -p /app/media /app/static

# Set this directory to be owned by the "wagtail" user. This Wagtail project
# uses SQLite, the folder needs to be owned by the user that
# will be writing to the database file.
RUN chown -R wagtail:wagtail /app

# Copy the source code of the project into the container.
COPY --chown=wagtail:wagtail . .

# Use user "wagtail" to run the build commands below and the server itself.
USER wagtail

# Runtime command that executes when "docker run" is called, it does the
# following:
#   1. Migrate the database.
#   2. Start the application server using gunicorn.conf.py.
CMD set -xe; python manage.py migrate --noinput; gunicorn mysite.wsgi:application --config gunicorn.conf.py

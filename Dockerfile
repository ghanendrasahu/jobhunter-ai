FROM python:3.11-slim

WORKDIR /app

ENV JOBHUNTER_ROOT=/app \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install system dependencies required by Playwright/Chromium
RUN apt-get update && apt-get install -y \
    wget gnupg libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching.
# requirements.txt is runtime-only; dev tooling stays out of the image.
COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
RUN pip install -r requirements.txt \
    && pip install -e . \
    && python -m playwright install chromium \
    && python -m playwright install-deps chromium \
    && rm -rf /root/.cache

# Runtime directories (writable by the non-root user).
RUN mkdir -p history resumes uploads data && \
    useradd --create-home --shell /usr/sbin/nologin jobhunter && \
    chown -R jobhunter:jobhunter /app

USER jobhunter

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

# Streamlit UI (default)
CMD ["jobhunter-web", "--server.port=8501", "--server.address=0.0.0.0"]

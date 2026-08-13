FROM python:3.11-slim

WORKDIR /app

ENV JOBHUNTER_ROOT=/app \
    PYTHONUNBUFFERED=1

# Install system dependencies required by Playwright/Chromium
RUN apt-get update && apt-get install -y \
    wget gnupg libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching
COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e .

# Install Playwright and its Chromium browser
RUN pip install --no-cache-dir playwright \
    && python -m playwright install chromium \
    && python -m playwright install-deps chromium

# Runtime directories
RUN mkdir -p history resumes uploads

EXPOSE 8501

# Streamlit UI (default)
CMD ["jobhunter-web", "--server.port=8501", "--server.address=0.0.0.0"]
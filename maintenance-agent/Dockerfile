FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates chromium curl fonts-noto-cjk fonts-noto-color-emoji git nodejs npm util-linux \
    && rm -rf /var/lib/apt/lists/*

RUN npm install --global @anthropic-ai/claude-code@2.1.205 \
    && claude --version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 maintainer \
    && mkdir -p /data /work \
    && chown -R maintainer:maintainer /home/maintainer /work

EXPOSE 8010

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]

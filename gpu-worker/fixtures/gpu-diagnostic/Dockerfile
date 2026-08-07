FROM nvidia/cuda:12.6.3-base-ubuntu24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app.py .
EXPOSE 7860
CMD ["python3", "app.py"]

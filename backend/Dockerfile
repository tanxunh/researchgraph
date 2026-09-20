FROM python:3.11-slim AS runtime

WORKDIR /app/backend
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ARG INSTALL_BGE=false
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY requirements-bge.txt ./requirements-bge.txt
RUN if [ "$INSTALL_BGE" = "true" ]; then \
      python -m pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu \
      && python -m pip install --no-cache-dir -r requirements-bge.txt; \
    fi && python -m pip check
COPY . .
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Test tools are installed only in the explicit test target.
FROM runtime AS test
COPY tests/support/release_gate_smoke.py /app/scripts/release_gate_smoke.py
COPY benchmarks/agent /agent-benchmark
COPY benchmarks/real_research /source-benchmark
RUN python -m pip install --no-cache-dir -r requirements-dev.txt \
    && python -m pip check
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider"]

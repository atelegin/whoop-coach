# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir hatchling

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Build wheel
RUN pip wheel --no-deps --wheel-dir /wheels .

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Copy wheel from builder
COPY --from=builder /wheels/*.whl /wheels/

# Install the package
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Copy alembic config
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Create startup script that runs migrations then starts app
RUN echo '#!/bin/bash\nset -e\nalembic upgrade head\nexec uvicorn whoop_coach.main:app --host 0.0.0.0 --port $PORT' > /app/start.sh && chmod +x /app/start.sh

# Create non-root user
RUN useradd --create-home appuser
USER appuser

# Default port (Railway overrides with $PORT)
ENV PORT=8000
EXPOSE $PORT

# Run startup script
CMD ["/bin/bash", "/app/start.sh"]

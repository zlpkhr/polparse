# Use official Python image
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY . .

# Install Python dependencies
RUN uv sync

# Expose port for mock server (main_test.py)
EXPOSE 5000

# Default command (can be overridden)
CMD ["uv", "run", "main.py"]

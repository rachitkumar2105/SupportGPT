FROM python:3.9-slim

WORKDIR /app

# Install necessary system dependencies for PyTesseract and psycopg2 if needed
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy all application files
COPY . .

# Create necessary directories and ensure proper permissions for Hugging Face Spaces
RUN mkdir -p docs uploads && \
    chmod -R 777 docs uploads && \
    touch app.db && \
    chmod 777 app.db

# Expose port (HF Spaces uses port 7860 by default for Docker spaces)
EXPOSE 7860

# Command to run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]

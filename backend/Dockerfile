FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTEMBED_CACHE_PATH=/home/app/.cache/fastembed \
    HF_HOME=/home/app/.cache/huggingface \
    DATABASE_URL=sqlite:////home/app/data/supportgpt.db

# Hugging Face Spaces run containers as uid 1000; never run as root.
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /home/app/api /home/app/data \
 && chown -R app:app /home/app
WORKDIR /home/app/api

COPY requirements.txt .
RUN pip install -r requirements.txt

USER app
# Bake the embedding model into the image so a cold start doesn't download it.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/home/app/.cache/fastembed')"

COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/api/health').status==200 else 1)"
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-server-header --timeout-graceful-shutdown 10"]

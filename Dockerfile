FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE=/data/simhub.sqlite \
    SIMHUB_UID=10001 \
    SIMHUB_GID=10001

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY docker-drop-privileges.py /usr/local/bin/docker-drop-privileges

RUN groupadd --gid "${SIMHUB_GID}" simhub \
    && useradd --uid "${SIMHUB_UID}" --gid simhub --home-dir /app --no-create-home --shell /usr/sbin/nologin simhub \
    && mkdir -p /data \
    && chown -R simhub:simhub /data /app \
    && chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/docker-drop-privileges

EXPOSE 8080

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app.main:app"]

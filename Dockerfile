FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.lock ./
COPY third_party ./third_party
RUN pip install --upgrade pip \
    && pip install -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
COPY skills ./skills
RUN pip install . --no-deps
RUN addgroup --system learningloop \
    && adduser --system --ingroup learningloop learningloop \
    && mkdir -p /data \
    && chown -R learningloop:learningloop /data
COPY docker-entrypoint.sh /usr/local/bin/learningloop-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/learningloop-entrypoint \
    && chmod 755 /usr/local/bin/learningloop-entrypoint

VOLUME ["/data"]
EXPOSE 8765
ENTRYPOINT ["/usr/local/bin/learningloop-entrypoint"]
CMD ["learningloop", "serve", "--host", "0.0.0.0", "--port", "8765"]

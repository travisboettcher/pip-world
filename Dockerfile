FROM python:3.12-slim
ARG VERSION=dev
ARG REVISION=
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_VERSION=$VERSION PIP_REVISION=$REVISION
WORKDIR /srv
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY web ./web
RUN useradd -u 10001 -m agent && mkdir /data && chown agent /data
USER agent
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=2s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

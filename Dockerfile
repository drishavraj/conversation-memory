FROM node:22-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY --from=frontend /build/app/static ./app/static
COPY migrations ./migrations
COPY alembic.ini .
COPY start.sh /app/start.sh
CMD ["sh", "/app/start.sh"]

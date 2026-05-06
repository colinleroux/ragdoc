FROM node:20-alpine AS frontend
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY src ./src
COPY app/templates ./app/templates
COPY tailwind.config.js postcss.config.js vite.config.js ./
RUN npm run build

FROM python:3.12-slim AS backend
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /app/app/static/vite ./app/static/vite

RUN mkdir -p /app/instance
EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "wsgi_app:application"]

FROM nginx:1.27-alpine AS nginx
COPY nginx/default.conf /etc/nginx/conf.d/default.conf

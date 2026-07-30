FROM python:3.14-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# --- Static files ---
# Uncomment to collect static files at build time.
# Requires DJANGO_SECRET_KEY to be set (use a build ARG or pass --build-arg).
# ARG DJANGO_SECRET_KEY=build-placeholder
# ENV DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
# RUN python manage.py collectstatic --noinput

EXPOSE 8000

# Development / default: Django's built-in server.
# For production, install gunicorn (add to requirements.txt) and use:
#   CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

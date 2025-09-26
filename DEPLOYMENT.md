# Deployment

## Quick evaluation

For local testing without any configuration (requires [Docker Desktop](https://www.docker.com/products/docker-desktop/)):

```powershell

# Launch evaluation instance
docker compose -f docker-compose.eval.yml up -d --build
```

Open http://127.0.0.1:8000 and create your first user account.

> **⚠️ Warning**: Uses default settings - not for production! The database is stored in a Docker volume and uses SQLite.

## Production deployment

### [Docker Compose](https://docs.docker.com/compose/) (recommended)

For web deployment with automatic SSL certificates and PostgreSQL database:

1. **Create a full environment file**:
   ```powershell
   cp .env.example .env
   ```

2. **Edit `.env` file to include your deployment domain and secret key**:
   ```bash
   BOMNADO_DOMAIN=yourdomain.com
   DJANGO_SECRET_KEY=your-secret-key-here
   ```

3. **Launch**:
   ```powershell
   docker compose up -d --build
   ```

Caddy will automatically obtain SSL certificates via Let's Encrypt. Open `https://yourdomain.com`.

*Note: Production deployments use PostgreSQL and Redis.*

### Custom deployment

Use the `Dockerfile` with your own setup:
- PostgreSQL database
- Redis cache
- Web server (nginx, Apache, etc.)
- SSL certificates

Set required environment variables in your `.env` file.

## Environment variables

Create a `.env` file in the project root:

### Required

- `DJANGO_SECRET_KEY` - Generate with `python ./generate_secret_key.py`

### Required for production deployment

- `BOMNADO_DOMAIN` - Your domain name (e.g., `example.com`)
- `DJANGO_ALLOWED_HOSTS` - Comma-delimited list (e.g., `example.com,www.example.com`)
- `CSRF_TRUSTED_ORIGINS` - HTTPS origins (e.g., `https://example.com,https://www.example.com`)
- `POSTGRES_USER` - PostgreSQL username
- `POSTGRES_PASSWORD` - PostgreSQL password
- `POSTGRES_DB` - Database name (defaults to `bomnado`)
- `POSTGRES_HOST` - Database hostname (defaults to `db` in Docker Compose)

### Optional services

- **Email**: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`
- **Monitoring**: `SENTRY_DSN`, `SENTRY_ENVIRONMENT`
- **Backups**: `USE_DROPBOX_BACKUPS`, `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, etc.
- **Advanced**: `POSTGRES_PORT`, `REDIS_LOCATION`, `DJANGO_SETTINGS_MODULE`

See `.env.example` for a complete template. Most settings have sensible defaults when using Docker Compose.

## Environment variables reference

Some of these are already set to default when using the default docker-compose configuration.

### Core Configuration

- `DJANGO_ALLOWED_HOSTS`
    : The list of allowed hosts that Bomnado can accept requests from
    : It is a list of comma-delimited values, e.g. `foo.com,bar.com`
    : e.g. `DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost`

- `CSRF_TRUSTED_ORIGINS`
    : A list of allowed origins for unsafe requests for CSRF prevention. Required when using HTTPS.
    : See [Django docs](https://docs.djangoproject.com/en/5.2/ref/settings/#csrf-trusted-origins) for more information
    : e.g. `CSRF_TRUSTED_ORIGINS=https://127.0.0.1,https://localhost`

- `POSTGRES_USER`
    : The username to use for the PostgreSQL database instance

- `POSTGRES_PASSWORD`
    : The password to use for the `POSTGRES_USER`

- `POSTGRES_DB`
    : The name of the PostgreSQL database to use
    : In the `docker-compose.yml` this is set to `bomnado` by default

- `POSTGRES_HOST`
    : The hostname of the PostgreSQL database
    : In the `docker-compose.yml` this is set to `db`

### Other Configuration

- `DJANGO_SETTINGS_MODULE`
    : The Django settings module to use. Options are `bomnado.settings.development` and `bomnado.settings.production`
    : In `development`, an SQLite database is used with no external services required.
    : In `production`, PostgreSQL, Redis, and Celery instances are required. Email service, Sentry, and Dropbox backups are also enabled.
    : Generally, `development` is the default when working with the project as normal with `pdm`, or with the `docker-compose.eval.yml` file, and `production` is used when running Bomnado with a `wsgi`-compatible server.

- `POSTGRES_PORT`
    : The port that PostgreSQL is running on
    : Default: `5432`

- `REDIS_LOCATION`
    : The location of the local redis instance
    : Default: `redis://redis:6379`

### Extras

#### Sentry

- `SENTRY_DSN`
    : The DSN of your Sentry project you wish to send Bomnado logs to. If this is not present then Sentry will be disabled

- `SENTRY_ENVIRONMENT`
    : The sentry environment string to use.
    : Defaults to `production`

#### Emails

<!-- TODO just link to Django docs here? -->
- `EMAIL_MODE`
    : `email` or `console` - `console` mode just outputs any emails to the server console.
    : if `email` is used, the email settings below must also be set.
    : `email` is the default in production. If in development mode, the console will always be used.

- `EMAIL_HOST`
    : The host to send emails from e.g. `smtp.gmail.com`

- `EMAIL_PORT`
    : The port of the SMTP server on `EMAIL_HOST`

- `EMAIL_HOST_USER`
    : The username to use with `EMAIL_HOST`

- `EMAIL_HOST_PASSWORD`
    : `EMAIL_HOST_USER`'s password

- `EMAIL_USE_TLS`
    : whether to use a secure TLS connection when talking to the SMTP server
    : Defaults to `False`

- `DEFAULT_FROM_EMAIL`
    : The default email address to send emails from for user notifications, password recovery, etc.

#### Backups

Database backups are enabled by default

- `DBBACKUP_CLEANUP_KEEP`
    : How many of the daily backups to keep. When the number of backups exceeds this number, the oldest backups will be deleted.
    : Default `7`

- `DBBACKUP_CLEANUP_KEEP_MEDIA`
    : How many of the daily media backups to keep. When the number of backups exceeds this number, the oldest backups will be deleted.
    : Default `7`

- `BACKUP_TIME`
    : The time of day to perform database backups in the format "HH:mm"
    : Default: `05:00`

- `DBBACKUP_ADMINS`
    : The list of people who will be emailed if the backup fails for any reason
    : It is a list of comma-delimited values of names and emails e.g. `John Johnson,john@foo.com,Tim Timpson,tim@bar.com`

#### Dropbox Backups

- `USE_DROPBOX_BACKUPS`
    : Whether to use the Dropbox integration for backups
    : Default: `False`

- `DROPBOX_ROOT_PATH`
    : Where to save database backups in Dropbox

Please refer to [this documentation](https://django-cloud-storages.readthedocs.io/en/latest/backends/dropbox.html) to configure these authentication options:

- `DROPBOX_APP_KEY`
- `DROPBOX_APP_SECRET` 
- `DROPBOX_OAUTH2_TOKEN`
- `DROPBOX_OAUTH2_REFRESH_TOKEN`

# Production Deploy

This service runs as a Docker Compose app on the Oracle server.

## Server prerequisites

Install Docker and Docker Compose plugin on the server, then create an app directory:

```bash
sudo mkdir -p /opt/splitwise-arbitrage/state
sudo chown -R "$USER":"$USER" /opt/splitwise-arbitrage
```

Create `/opt/splitwise-arbitrage/.env` on the server using the same keys from local `.env`.
Keep `DRY_RUN=false` for production and set the daily schedule:

```env
DRY_RUN=false
SCHEDULE_TIME=06:00
SCHEDULE_TIMEZONE=America/Buenos_Aires
```

## GitHub repository secrets

Add these secrets in GitHub:

- `ORACLE_SSH_HOST`: server public IP or DNS name.
- `ORACLE_SSH_USER`: SSH user that can run Docker.
- `ORACLE_SSH_KEY`: private key for that user.
- `ORACLE_SSH_PORT`: SSH port, usually `22`.
- `ORACLE_APP_DIR`: app directory, for example `/opt/splitwise-arbitrage`.

The GitHub Action builds the image, pushes it to GHCR, uploads the compose file,
pulls the new image on the server, and restarts the container.

## Manual server smoke test

```bash
cd /opt/splitwise-arbitrage
docker compose run --rm splitwise-arbitrage python -m splitwise_arbitrage validate
docker compose run --rm splitwise-arbitrage python -m splitwise_arbitrage plan
```

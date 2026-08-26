# Dokploy / Docker Compose Deployment

Bu proje Docker Compose ile kendi PostgreSQL ve Redis servislerini kullanacak sekilde hazirlanmistir.
Windows gelistirmede Memurai kullanilabilir, ancak canli Ubuntu/Dokploy ortaminda Memurai gerekmez.
Compose icindeki `redis:7-alpine` servisi Celery, cache, rate limit ve websocket icin standart Redis olarak calisir.

## Lokal Docker Test

```bash
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs -f web
```

Uygulama lokal testte Nginx gateway uzerinden su adreste acilir:

```text
http://localhost:8080/admin/login/
```

## Dokploy

1. Projeyi Git repo olarak Dokploy'a bagla.
2. Deploy type olarak Docker Compose sec.
3. Compose dosyasi olarak `docker-compose.yml` kullan.
4. Environment degiskenlerini `.env.production.example` uzerinden gir. Dokploy'un
   olusturdugu `.env` dosyasi Compose servisleri tarafindan otomatik okunur.
5. Domain'i `gateway` servisine ve container portu `8080`'e bagla.
6. Domain icin `ALLOWED_HOSTS` ve `CSRF_TRUSTED_ORIGINS` degerlerini canli domain ile guncelle.
7. Dokploy HTTPS verdiginde su degerler canlida acik olmali:

```env
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
USE_X_FORWARDED_HOST=True
```

## Servisler

- `web`: Django ASGI uygulamasi, Daphne ile calisir.
- `gateway`: Nginx reverse proxy; `/media/` dosyalarini sunar ve kalan trafigi `web` servisine aktarir.
- `worker`: Celery worker. `default,sync,ai,marketplace,maintenance,billing,reports,notifications` kuyruklarini dinler.
- `beat`: Celery scheduled tasks.
- `db`: PostgreSQL 16.
- `redis`: Redis 7, Celery/cache/websocket/rate-limit icin kullanilir.

Yalnizca `gateway:8080` host'a acilir. `web`, PostgreSQL ve Redis Docker agi icinde kalir.
PostgreSQL container'i `DB_NAME`, `DB_USER` ve zorunlu `DB_PASSWORD` degerlerini environment'tan alir.

`DB_HOST=db` ve `REDIS_HOST=redis` kalmalidir. Bunlar Docker agi icindeki servis adlaridir.

## Redis ve Cache

Canlida `CACHE_REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` ve `CHANNEL_REDIS_URL` degerleri Redis servislerine bakmalidir:

```env
CACHE_REDIS_URL=redis://redis:6379/3
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
CHANNEL_REDIS_URL=redis://redis:6379/2
```

`CACHE_REDIS_URL` bos kalirsa Django LocMem cache'e duser. Bu lokal test icin kabul edilebilir ama canlida rate limit sayaclari worker/process bazinda ayrisacagi icin kullanilmamalidir.

## Canli Oncesi Kontrol

```bash
python manage.py check
python manage.py launch_check --strict
```

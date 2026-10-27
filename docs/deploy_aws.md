# Deploying the decision console to AWS (Lightsail containers)

The whole platform ships as one Docker image: the React dashboard plus the FastAPI decision API.
It runs on an Amazon Lightsail container service, which gives a public HTTPS URL.

## 1. Build and test the image locally

```bash
python -m api.export                       # api/bundle/: model, policy, results
docker build -t credit-console .
docker run --rm -p 8000:8000 credit-console    # http://localhost:8000
```

## 2. Push it to Docker Hub

Lightsail runs x86 servers, so build for `linux/amd64` (needed on Apple Silicon Macs).

```bash
docker login
docker buildx build --platform linux/amd64 -t <dockerhub-user>/credit-console:1.0 --push .
```

The image holds the trained model, the policy table and 500 sample applications from the public
Lending Club dataset. `.dockerignore` keeps `.env`, `kaggle.json`, raw data and the git history out.

## 3. Create the Lightsail container service

Lightsail console, then Containers, then Create container service:

| Setting | Value |
| --- | --- |
| Region | US East (N. Virginia) |
| Power | Micro (1 GB RAM), scale 1 |
| Container name | `api` |
| Image | `<dockerhub-user>/credit-console:1.0` |
| Open ports | `8000`, HTTP |
| Public endpoint | container `api`, port 8000, health check path `/api/health` |

Deployment takes about 5 minutes. The service URL (`https://<name>.<id>.<region>.cs.amazonlightsail.com`) serves the
dashboard at `/`, the API at `/api/...` and the interactive docs at `/docs`.

## 4. Load-test the live service

```bash
python -m api.loadtest --url https://<your-service-url> --requests 1000 --concurrency 10
```

## Cost

Micro is $10/month; new Lightsail users get the first 3 months free. To stop charges, delete the container
service.

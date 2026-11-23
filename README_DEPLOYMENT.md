# AI Travel Planner — Docker + GCP Cloud Run deployment

## What is included

- `Dockerfile`: packages the Flask app and dependencies into a container.
- `.dockerignore`: prevents local files and secrets from entering the image.
- `.github/workflows/deploy.yml`: GitHub Actions pipeline. Pushes to `main` build an image using Cloud Build and deploy it to Cloud Run.
- `/health`: lightweight health endpoint.
- `.env.example`: local configuration template only. The uploaded `.env` (which contained a credential) is intentionally excluded.

## Architecture

Developer pushes code to GitHub `main`
  -> GitHub Actions authenticates to Google Cloud with Workload Identity Federation
  -> Cloud Build builds the Docker image
  -> Artifact Registry stores the versioned image
  -> Cloud Run starts the container and serves HTTPS traffic
  -> Flask calls Gemini, DuckDuckGo search, and Open-Meteo as needed

## Before deploying

1. Revoke the API key that was included in the uploaded ZIP and create a new one.
2. Create/select a Google Cloud project and enable billing.
3. Enable these APIs: Cloud Run, Cloud Build, Artifact Registry, Secret Manager, and IAM Service Account Credentials.
4. Create an Artifact Registry Docker repository in `asia-south1` (Mumbai), for example `travel-planner`.
5. Store the new key in Secret Manager as `travel-planner-google-api-key`.
6. Configure Workload Identity Federation for your GitHub repository and create a deploy service account. Grant only the roles needed for Cloud Build submission, Artifact Registry image upload, Cloud Run deployment, and service-account use. Grant the Cloud Run runtime service account `Secret Manager Secret Accessor` on the API-key secret.
7. In GitHub repository Settings -> Secrets and variables -> Actions -> Variables, add:
   - `GCP_PROJECT_ID`: Google Cloud project ID
   - `GCP_REGION`: `asia-south1`
   - `AR_REPOSITORY`: Artifact Registry repository name
   - `CLOUD_RUN_SERVICE`: `ai-travel-planner`
   - `GCP_WIF_PROVIDER`: full Workload Identity Provider resource name
   - `GCP_DEPLOY_SERVICE_ACCOUNT`: deploy service account email
8. Push this project to the GitHub repository's `main` branch. Open Actions to follow the pipeline logs.

The workflow intentionally does not contain an API key. The secret must exist before the first deployment. The GitHub Actions variables must be configured before running the workflow.

## Local Docker test

1. Copy `.env.example` to `.env` and put your new API key in `.env`.
2. Build: `docker build -t ai-travel-planner .`
3. Run: `docker run --rm -p 8080:8080 --env-file .env ai-travel-planner`
4. Open `http://localhost:8080`; check `http://localhost:8080/health`.

Never commit `.env`. The `.dockerignore` excludes it from the image build context.

## Important project limitations to address separately

- The current app performs several sequential LLM calls per trip. Cloud Run's request timeout is set to 300 seconds; long AI calls may still exceed it.
- Hotel prices returned by web search are not verified live booking prices. The app currently asks the model to estimate missing prices; treat those as estimates, not confirmed offers.
- Fuel price and mileage are hard-coded in `app.py` (₹105/litre, bike 45 km/l, other vehicles 15 km/l).
- Check Gemini API model access, quota, and billing for the selected key/project before production use.
- This deployment configuration is a starting point for a small learning project, not a security-reviewed production service. Review authentication/rate limits before exposing it publicly.

#!/usr/bin/env bash
# Deploy CLEARCUT to Cloud Run.
#
# Builds remotely with Cloud Build, so no local Docker daemon is needed.
# API keys go into Secret Manager rather than plain env vars, and are mounted
# into the service at runtime.
#
# Usage:  ./deploy.sh [PROJECT_ID] [REGION]

set -euo pipefail

PROJECT="${1:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${2:-us-central1}"
SERVICE="clearcut"

if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "No GCP project. Pass one:  ./deploy.sh my-project-id" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "No .env found — copy .env.example and fill in your keys first." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

: "${PARALLEL_API_KEY:?PARALLEL_API_KEY missing from .env}"
: "${GOOGLE_API_KEY:?GOOGLE_API_KEY missing from .env}"

echo "==> Project: ${PROJECT}   Region: ${REGION}"

echo "==> Enabling required APIs"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  --project "${PROJECT}"

# Store each key as a Secret Manager secret, adding a new version if it exists.
put_secret () {
  local name="$1" value="$2"
  if gcloud secrets describe "${name}" --project "${PROJECT}" >/dev/null 2>&1; then
    printf '%s' "${value}" | gcloud secrets versions add "${name}" \
      --data-file=- --project "${PROJECT}" >/dev/null
    echo "    updated secret ${name}"
  else
    printf '%s' "${value}" | gcloud secrets create "${name}" \
      --data-file=- --replication-policy=automatic --project "${PROJECT}" >/dev/null
    echo "    created secret ${name}"
  fi
}

echo "==> Writing secrets"
put_secret clearcut-parallel-key "${PARALLEL_API_KEY}"
put_secret clearcut-google-key   "${GOOGLE_API_KEY}"

# Grant the runtime service account read access to the secrets.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for s in clearcut-parallel-key clearcut-google-key; do
  gcloud secrets add-iam-policy-binding "${s}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role=roles/secretmanager.secretAccessor \
    --project "${PROJECT}" >/dev/null 2>&1 || true
done

# Vertex is the inference path, so the runtime account needs to call it. Without
# this the container falls back to the AI Studio endpoint and every model call
# fails on whatever prepay balance that key happens to have.
echo "==> Granting Vertex AI access to the runtime service account"
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role=roles/aiplatform.user --condition=None >/dev/null 2>&1 || true

echo "==> Building and deploying (Cloud Build)"
gcloud run deploy "${SERVICE}" \
  --source . \
  --project "${PROJECT}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 900 \
  --concurrency 8 \
  --max-instances 4 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=TRUE,CLEARCUT_DATA_DIR=/tmp/clearcut" \
  --set-secrets "PARALLEL_API_KEY=clearcut-parallel-key:latest,GOOGLE_API_KEY=clearcut-google-key:latest"

URL="$(gcloud run services describe "${SERVICE}" --project "${PROJECT}" --region "${REGION}" --format='value(status.url)')"
echo
echo "==> Live at: ${URL}"
echo "    health:  ${URL}/api/health"

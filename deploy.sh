#!/usr/bin/env bash
# Deploy git-release to GCP Cloud Functions + Cloudflare Pages
set -euo pipefail

PROJECT="git-release-496817"
REGION="us-central1"
FUNCTION="git-release"
BUCKET="git-release-releases"
SA="git-release-sa@${PROJECT}.iam.gserviceaccount.com"

echo "==> 1. Create GCS-compatible R2 bucket (manual step — do in Cloudflare dashboard)"
echo "    Dashboard → R2 → Create bucket → name: ${BUCKET}"
echo "    Then create R2 API token with Object Read & Write scope."
echo ""

echo "==> 2. Store secrets in GCP Secret Manager"
read -rsp "GROQ_API_KEY: " GROQ_KEY; echo
echo -n "$GROQ_KEY" | gcloud secrets create GROQ_API_KEY --data-file=- --project="$PROJECT" 2>/dev/null \
  || echo -n "$GROQ_KEY" | gcloud secrets versions add GROQ_API_KEY --data-file=- --project="$PROJECT"

read -rsp "GITHUB_TOKEN (optional, press Enter to skip): " GH_TOKEN; echo
if [[ -n "$GH_TOKEN" ]]; then
  echo -n "$GH_TOKEN" | gcloud secrets create GITHUB_TOKEN --data-file=- --project="$PROJECT" 2>/dev/null \
    || echo -n "$GH_TOKEN" | gcloud secrets versions add GITHUB_TOKEN --data-file=- --project="$PROJECT"
fi

TRIGGER_SECRET=$(openssl rand -hex 32)
echo -n "$TRIGGER_SECRET" | gcloud secrets create TRIGGER_SECRET --data-file=- --project="$PROJECT" 2>/dev/null \
  || echo -n "$TRIGGER_SECRET" | gcloud secrets versions add TRIGGER_SECRET --data-file=- --project="$PROJECT"
echo "  TRIGGER_SECRET = $TRIGGER_SECRET  (save this)"

read -rsp "R2_ACCESS_KEY_ID: " R2_KEY_ID; echo
echo -n "$R2_KEY_ID" | gcloud secrets create R2_ACCESS_KEY_ID --data-file=- --project="$PROJECT" 2>/dev/null \
  || echo -n "$R2_KEY_ID" | gcloud secrets versions add R2_ACCESS_KEY_ID --data-file=- --project="$PROJECT"

read -rsp "R2_SECRET_ACCESS_KEY: " R2_SECRET; echo
echo -n "$R2_SECRET" | gcloud secrets create R2_SECRET_ACCESS_KEY --data-file=- --project="$PROJECT" 2>/dev/null \
  || echo -n "$R2_SECRET" | gcloud secrets versions add R2_SECRET_ACCESS_KEY --data-file=- --project="$PROJECT"

read -rsp "R2_ACCOUNT_ID (Cloudflare account ID): " R2_ACCOUNT; echo
echo -n "$R2_ACCOUNT" | gcloud secrets create R2_ACCOUNT_ID --data-file=- --project="$PROJECT" 2>/dev/null \
  || echo -n "$R2_ACCOUNT" | gcloud secrets versions add R2_ACCOUNT_ID --data-file=- --project="$PROJECT"

echo ""
echo "==> 3. Create service account and grant roles"
gcloud iam service-accounts create git-release-sa \
  --display-name="git-release Cloud Function" \
  --project="$PROJECT" 2>/dev/null || true

for ROLE in roles/secretmanager.secretAccessor roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${SA}" \
    --role="$ROLE" --quiet
done

echo ""
echo "==> 4. Deploy Cloud Function (gen2)"
gcloud functions deploy "$FUNCTION" \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source=. \
  --entry-point=main \
  --trigger-http \
  --allow-unauthenticated \
  --service-account="$SA" \
  --memory=512MB \
  --timeout=300s \
  --project="$PROJECT"

FUNCTION_URL=$(gcloud functions describe "$FUNCTION" \
  --region="$REGION" --project="$PROJECT" \
  --format="value(serviceConfig.uri)")
echo "  Function URL: $FUNCTION_URL"

echo ""
echo "==> 5. Create Cloud Scheduler job (daily at 06:00 UTC)"
gcloud scheduler jobs create http "${FUNCTION}-daily" \
  --schedule="0 6 * * *" \
  --uri="${FUNCTION_URL}/trigger" \
  --http-method=POST \
  --headers="X-Trigger-Secret=${TRIGGER_SECRET}" \
  --time-zone="UTC" \
  --location="$REGION" \
  --project="$PROJECT" 2>/dev/null \
  || gcloud scheduler jobs update http "${FUNCTION}-daily" \
    --schedule="0 6 * * *" \
    --uri="${FUNCTION_URL}/trigger" \
    --http-method=POST \
    --headers="X-Trigger-Secret=${TRIGGER_SECRET}" \
    --time-zone="UTC" \
    --location="$REGION" \
    --project="$PROJECT"

echo ""
echo "==> 6. Inject Cloud Function URL into frontend and deploy to Cloudflare Pages"
sed -i.bak "s|https://REPLACE_WITH_CLOUD_FUNCTION_URL|${FUNCTION_URL}|g" public/index.html
npx wrangler pages deploy public/ --project-name=git-release
# Restore template
sed -i.bak "s|${FUNCTION_URL}|https://REPLACE_WITH_CLOUD_FUNCTION_URL|g" public/index.html
rm -f public/index.html.bak

echo ""
echo "==> Done!"
echo "  Cloud Function : $FUNCTION_URL"
echo "  Manual trigger : curl -X POST -H 'X-Trigger-Secret: $TRIGGER_SECRET' $FUNCTION_URL/trigger"

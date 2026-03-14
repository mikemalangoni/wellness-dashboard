#!/bin/sh
# Write Google credentials from environment variables to disk at startup
if [ -n "$GOOGLE_CREDENTIALS_JSON" ]; then
  echo "$GOOGLE_CREDENTIALS_JSON" > /app/credentials.json
fi

if [ -n "$GOOGLE_TOKEN_JSON" ]; then
  echo "$GOOGLE_TOKEN_JSON" > /app/token.json
fi

exec streamlit run app.py \
  --server.port=8080 \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false

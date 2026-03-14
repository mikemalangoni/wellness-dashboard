FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY google_auth.py spine_parser.py app.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

# credentials.json and token.json are written at runtime from Fly secrets
ENTRYPOINT ["/app/entrypoint.sh"]

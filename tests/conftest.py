import os

# Set required env vars before any import of the app.
# Use direct assignment (not setdefault) so test values always win,
# even if the env already has these variables set.
os.environ["MF_API_KEY"] = "test-api-key"
os.environ["MF_ADMIN_KEY"] = "test-admin-key"

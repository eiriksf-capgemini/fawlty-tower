# Fawlty Tower: one small image, many ways to misbehave.
#
# Every guest runs from this same image; FAWLTY_GUEST picks which one (see
# src/fawlty/dispatch.py). Build it, push it to your registry, and point one
# Deployment per guest at it.
FROM python:3.12-slim

# kubernetes client is only needed by the oreilly/chef guests; the rest use
# nothing but the stdlib. Kept tiny on purpose.
RUN pip install --no-cache-dir "kubernetes==31.0.0"

WORKDIR /app
COPY src/ /app/src/
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

# No default guest: the Deployment MUST set FAWLTY_GUEST. Running with none set
# exits non-zero with a helpful message rather than silently doing nothing.
ENTRYPOINT ["python", "-m", "fawlty.dispatch"]

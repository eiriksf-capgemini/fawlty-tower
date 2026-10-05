# Fawlty Tower: one small image, many ways to misbehave.
#
# Every guest runs from this same image; FAWLTY_GUEST picks which one (see
# src/fawlty/dispatch.py). Build it, push it to your registry, and point one
# Deployment per guest at it.
#
# For reproducible builds pin the base image by digest, e.g.
#   FROM python:3.12-slim@sha256:<digest>
# (`docker buildx imagetools inspect python:3.12-slim` prints the current one.)
FROM python:3.12-slim

# kubernetes client is only needed by the oreilly/chef guests; the rest use
# nothing but the stdlib. Kept tiny on purpose.
# The guests run as an unprivileged user by default; see USER below.
RUN pip install --no-cache-dir "kubernetes==31.0.0" \
    && useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin fawlty

WORKDIR /app
COPY src/ /app/src/
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Non-root by default, as a NUMERIC uid so `runAsNonRoot: true` can verify it.
# Every default-tier guest works unprivileged and with readOnlyRootFilesystem.
# Node-tier guests that need root (squatter binding host port 80, diskfill
# writing to a root-owned hostPath) must opt in explicitly in their Deployment
# with `securityContext: {runAsUser: 0}`; root is never the silent default.
USER 10001:10001

# No default guest: the Deployment MUST set FAWLTY_GUEST. Running with none set
# exits non-zero with a helpful message rather than silently doing nothing.
ENTRYPOINT ["python", "-m", "fawlty.dispatch"]

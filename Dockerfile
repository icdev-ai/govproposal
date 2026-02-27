# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
# -----------------------------------------------------------------
# GovProposal Portal — STIG-Hardened Container
# -----------------------------------------------------------------
# Ports:  5001/tcp  (Flask dashboard)
# Volumes: /app/data  (SQLite database persistence)
# -----------------------------------------------------------------

FROM python:3.11-slim AS base

# --- STIG: Metadata ---
LABEL maintainer="GovProposal System Administrator" \
      description="GovProposal Portal — DoD/IC Proposal Lifecycle Management" \
      classification="CUI // SP-PROPIN" \
      version="1.0.0"

# --- STIG: System hardening ---
# Install minimal OS deps, then clean up
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        tini && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# --- STIG: Non-root user (UID 1000) ---
RUN groupadd -r govproposal && \
    useradd -r -g govproposal -u 1000 -m -s /usr/sbin/nologin govproposal

# --- Application directory ---
WORKDIR /app

# --- Install Python dependencies (cached layer) ---
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn>=22.0

# --- Copy application code ---
COPY args/ /app/args/
COPY context/ /app/context/
COPY goals/ /app/goals/
COPY hardprompts/ /app/hardprompts/
COPY tools/ /app/tools/
COPY CLAUDE.md /app/CLAUDE.md

# --- Create data directory for SQLite ---
RUN mkdir -p /app/data /app/memory/logs && \
    chown -R govproposal:govproposal /app

# --- Copy entrypoint ---
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# --- STIG: Drop to non-root ---
USER govproposal

# --- Environment defaults ---
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    GOVPROPOSAL_DB_PATH=/app/data/govproposal.db \
    GOVPROPOSAL_SECRET=change-me-in-production \
    GOVPROPOSAL_CUI_BANNER="CUI // SP-PROPIN" \
    FLASK_PORT=5001

# --- Expose ports ---
# 5001: Flask dashboard (web UI + API)
EXPOSE 5001

# --- Persistent data ---
VOLUME ["/app/data"]

# --- Health check ---
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:5001/api/health || exit 1

# --- Startup via tini (PID 1 reaping) ---
ENTRYPOINT ["tini", "--"]
CMD ["/app/docker-entrypoint.sh"]

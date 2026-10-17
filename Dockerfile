FROM node:22-bookworm-slim

# Mirrors reachable from mainland China; override with --build-arg if deploying elsewhere
ARG APT_MIRROR=mirrors.cloud.tencent.com
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG PIP_INDEX=https://mirrors.cloud.tencent.com/pypi/simple
ARG PI_VERSION=0.99.2

RUN sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv git ca-certificates curl openssh-client \
      ripgrep fd-find jq procps less build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN npm config set registry "${NPM_REGISTRY}" --global \
 && npm install -g "@earendil-works/pi-coding-agent@${PI_VERSION}" \
 && npm cache clean --force

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -i "${PIP_INDEX}" -r /tmp/requirements.txt
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Bot code is bind-mounted (it is also a workspace), so edits + /restart take effect
WORKDIR /workspaces/ds-ai-wrapper
ENTRYPOINT ["entrypoint.sh"]
CMD ["python", "bot.py"]

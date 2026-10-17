#!/bin/sh
set -e

git config --global --add safe.directory '*'
[ -n "$GIT_USER_NAME" ] && git config --global user.name "$GIT_USER_NAME"
[ -n "$GIT_USER_EMAIL" ] && git config --global user.email "$GIT_USER_EMAIL"

# Route only github.com through the proxy
if [ -n "$GIT_PROXY" ]; then
    git config --global http.https://github.com/.proxy "$GIT_PROXY"
fi

if [ -n "$GITHUB_TOKEN" ]; then
    git config --global credential.helper store
    umask 077
    printf 'https://x-access-token:%s@github.com\n' "$GITHUB_TOKEN" > "$HOME/.git-credentials"
fi

exec "$@"

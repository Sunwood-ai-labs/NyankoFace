#!/bin/sh
set -eu

# Every Actions job receives its own Docker bridge. Docker maps the hostname
# "forgejo" to that bridge's gateway; this forwarder is the only service
# exposed there and relays requests to Forgejo on the outer actions network.
socat \
  TCP-LISTEN:3000,fork,reuseaddr \
  TCP:forgejo:3000 &

exec dockerd-entrypoint.sh "$@"

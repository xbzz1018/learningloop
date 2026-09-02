#!/bin/sh
set -eu

# Named volumes created by an older root container may need one-time ownership repair.
mkdir -p /data
chown -R learningloop:learningloop /data
exec runuser -u learningloop -- "$@"

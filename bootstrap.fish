#! /usr/bin/env fish

set gitUser (git config --global user.name)
set gitEmail (git config --global user.email)

flux bootstrap github \
  --owner=jetersen \
  --repository=homelab \
  --branch=main \
  --path=clusters/homelab \
  --personal \
  --author-name="$gitUser" \
  --author-email="$gitEmail" \

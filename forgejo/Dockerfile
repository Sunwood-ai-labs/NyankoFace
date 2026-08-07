# NyankoFace — customized Forgejo image
#
# We don't fork Forgejo; instead we bake the official "custom" override
# mechanism (templates + static assets) into the image and point
# GITEA_CUSTOM at it. curl is already present in the upstream image and is
# used by the compose healthcheck, so no extra packages are installed.
FROM codeberg.org/forgejo/forgejo:16

ENV GITEA_CUSTOM=/custom

COPY custom/ /custom/

# Brand outputs are derived from the same checked-in cat mark used by the
# portal. A named build context keeps Forgejo's raw overrides synchronized
# without making the whole repository the Docker context.
COPY --from=frontend_assets public/brand/nyankoface-cat-logo.png /custom/public/assets/img/logo.png
COPY --from=frontend_assets public/brand/favicon.svg /custom/public/assets/img/favicon.svg
COPY --from=frontend_assets public/brand/favicon-32x32.png /custom/public/assets/img/favicon.png
COPY --from=frontend_assets app/favicon.ico /custom/public/assets/img/favicon.ico
COPY --from=frontend_assets app/apple-icon.png /custom/public/assets/img/apple-touch-icon.png
COPY --from=frontend_assets public/brand/mask-icon.svg /custom/public/assets/img/mask-icon.svg

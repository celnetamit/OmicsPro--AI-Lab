# The web image: build the React app, then serve the static bundle from nginx,
# which also proxies /api to the API service so the browser only ever sees one
# origin and no CORS preflight is involved.
FROM node:20-alpine AS build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Stamped into the footer so a running deployment can be identified.
ARG VITE_RELEASE=dev
ENV VITE_RELEASE=$VITE_RELEASE
# Where NanoSchool is, for the governance screens. The runtime stage repeats it
# so the content-security policy names the same host the bundle calls.
ARG VITE_HUB_URL=https://live-labs.org
ENV VITE_HUB_URL=$VITE_HUB_URL
# Local runs with no hub at all. Leave it unset for anything hosted: with it on,
# the gate asks the API for a development session instead of verifying a launch.
# The API refuses that in production, so a build made with this by mistake fails
# closed — it says the API has no development session rather than opening the lab.
ARG VITE_DISABLE_LAB_AUTH
ENV VITE_DISABLE_LAB_AUTH=$VITE_DISABLE_LAB_AUTH
RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY docker/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /build/dist /usr/share/nginx/html

ARG VITE_HUB_URL=https://live-labs.org
ENV API_UPSTREAM=http://api:8000 \
    PORT=8080 \
    HUB_ORIGIN=$VITE_HUB_URL

EXPOSE 80 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

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
RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY docker/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /build/dist /usr/share/nginx/html

ENV API_UPSTREAM=http://api:8000 \
    PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

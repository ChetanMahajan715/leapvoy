# Web app for the server: Expo web export, served by nginx with the API behind /api (same address → no CORS).
# Build context = repo root. Multi-arch images → builds on Oracle ARM64.
FROM node:24-alpine AS build
WORKDIR /app/mobile
COPY mobile/package.json mobile/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY mobile ./
# Same address as the page: the browser calls /api/... on the server it was loaded from
ENV EXPO_PUBLIC_API_URL=/api
RUN npx expo export -p web

FROM nginx:1.29-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/mobile/dist /usr/share/nginx/html

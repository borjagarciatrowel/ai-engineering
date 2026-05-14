# Local-development image for the Angular dev server with hot reload.
# For a production-grade image, do a multi-stage build with nginx serving dist/.
FROM node:20-alpine

WORKDIR /app

# Install dependencies first so they are cached when only source files change.
COPY package.json package-lock.json ./
RUN npm ci

# Copy the rest of the project. In docker-compose we bind-mount src/ on top
# of this layer to get hot reload.
COPY . .

EXPOSE 4200

# Bind to 0.0.0.0 so the dev server is reachable from the host, and use the
# docker-specific proxy config that targets the API container via the host
# gateway instead of localhost.
CMD ["npx", "ng", "serve", "--host", "0.0.0.0", "--port", "4200", "--proxy-config", "proxy.conf.docker.json"]

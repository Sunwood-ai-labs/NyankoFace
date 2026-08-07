FROM nginx:alpine

RUN apk add --no-cache openssl

COPY docker-entrypoint.d/10-nyankoface-tls.sh /docker-entrypoint.d/10-nyankoface-tls.sh
RUN chmod +x /docker-entrypoint.d/10-nyankoface-tls.sh

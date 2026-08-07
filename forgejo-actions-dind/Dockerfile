FROM docker:27-dind

RUN apk add --no-cache socat

COPY entrypoint.sh /usr/local/bin/nyankoface-dind-entrypoint.sh
RUN chmod +x /usr/local/bin/nyankoface-dind-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/nyankoface-dind-entrypoint.sh"]

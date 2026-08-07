FROM alpine:3.20

RUN apk add --no-cache curl jq git bash docker-cli

COPY seed.sh /seed.sh
COPY catalog/ /catalog/
COPY templates/ /templates/
COPY assets/ /assets/
RUN sed -i 's/\r$//' /seed.sh && chmod +x /seed.sh

ENTRYPOINT ["/bin/bash", "/seed.sh"]

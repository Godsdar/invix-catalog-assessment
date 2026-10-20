# Build the official upstream release: public image registries may no longer serve MinIO.
FROM golang:1.24.8-alpine AS build
WORKDIR /src
ADD https://codeload.github.com/minio/minio/tar.gz/9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a /tmp/minio.tar.gz
RUN tar -xzf /tmp/minio.tar.gz --strip-components=1 && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/minio .

FROM alpine:3.22
RUN apk add --no-cache ca-certificates curl tzdata && \
    adduser -D -u 10001 minio && mkdir /data && chown minio:minio /data
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /src/LICENSE /licenses/MinIO-LICENSE
USER minio
ENV HOME=/tmp
EXPOSE 9000
ENTRYPOINT ["minio"]
CMD ["server", "/data"]

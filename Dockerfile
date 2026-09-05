FROM python:3.12-slim
WORKDIR /app
COPY edge_node ./edge_node
EXPOSE 8000
ENTRYPOINT []


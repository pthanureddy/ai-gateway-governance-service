FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md constraints.txt ./
COPY src ./src
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10001 --create-home gateway && mkdir /data && chown gateway /data
COPY config ./config
USER 10001
ENV DATABASE_URL=sqlite:////data/gateway.db
EXPOSE 8080
CMD ["uvicorn","ai_gateway.api:create_app","--factory","--host","0.0.0.0","--port","8080"]

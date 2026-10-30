FROM ghcr.io/astral-sh/uv AS uv_bin

FROM python:3.12-slim

COPY --from=uv_bin /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml .

COPY uv.lock .

RUN uv sync

COPY . .

EXPOSE 8000

CMD ["uv", "run" ,"uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
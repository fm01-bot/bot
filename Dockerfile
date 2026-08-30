FROM python:3.12-slim

RUN pip install uv

WORKDIR /bot

COPY . .

CMD ["uv", "run", "main.py"]

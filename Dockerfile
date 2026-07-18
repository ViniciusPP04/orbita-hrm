FROM python:3.12-slim
WORKDIR /app
COPY . .
EXPOSE 4173
CMD ["python", "server.py"]

FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV ORBITA_HRM_HOST=0.0.0.0
EXPOSE 4173
CMD ["python", "server.py"]

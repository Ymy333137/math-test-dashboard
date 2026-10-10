FROM mirror.ccs.tencentyun.com/library/python:3.13-slim
WORKDIR /service
COPY server.py refresh_client.py ./
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
CMD ["python", "server.py"]

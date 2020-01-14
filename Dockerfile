FROM python:3.8-slim

RUN python -m pip install --no-cache-dir boto3==1.*

WORKDIR /app
COPY s3-glacier-restore.py ./

ENTRYPOINT ["./s3-glacier-restore.py"]

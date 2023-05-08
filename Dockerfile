FROM --platform=linux/amd64 prefecthq/prefect:2.10.6-python3.11

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

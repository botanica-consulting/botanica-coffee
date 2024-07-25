FROM python:3.12-slim

WORKDIR /monitor

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY monitor.py monitor.py

CMD ["python", "monitor.py"]

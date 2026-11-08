FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py admin.py ./
ENV DATA_DIR=/data PORT=8787
EXPOSE 8787
CMD ["python", "server.py"]

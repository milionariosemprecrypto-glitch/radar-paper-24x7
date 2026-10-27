FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends bash && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1 BOT_CMD="python bot.py" PY=python
RUN mkdir -p data logs reports
EXPOSE 10000
CMD ["python", "render_entry.py"]

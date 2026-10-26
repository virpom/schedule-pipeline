FROM python:3.11-slim

# Без этого stdout/stderr буферизуются и docker logs показывает пустоту:
# при падении контейнера последние строки теряются.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY . .

CMD ["python", "main.py"]

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt setup.py README.md ./
COPY zikra/ ./zikra/

RUN pip install --no-cache-dir -e ".[postgres]"

EXPOSE 8100

CMD ["python3", "-m", "zikra", "--no-onboarding"]

FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt setup.py README.md ./
COPY zikra/ zikra/
COPY prompts/ prompts/
COPY scripts/ scripts/
RUN pip install --no-cache-dir -r requirements.txt -e ".[postgres]" \
    && addgroup --system --gid 10001 zikra \
    && adduser --system --uid 10001 --gid 10001 --no-create-home zikra \
    && chmod 0555 /app/scripts/container-entrypoint.sh /app/scripts/migrate_sqlite_to_postgres.py /app/scripts/require-migration.py

USER 10001:10001
EXPOSE 8377
ENTRYPOINT ["/app/scripts/container-entrypoint.sh"]
CMD ["python", "-m", "zikra", "--no-onboarding"]

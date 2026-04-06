import httpx
import os
import logging

logger = logging.getLogger(__name__)

_ZERO = [0.0] * 1536


async def embed(text: str) -> list:
    # Read env vars here (not at import time) so load_dotenv() has already run
    api_key = os.getenv('OPENAI_API_KEY', '')
    api_base = os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1')
    model = os.getenv('ZIKRA_EMBEDDING_MODEL', 'text-embedding-3-small')

    if not text or not text.strip():
        return _ZERO

    if not api_key:
        logger.warning('OPENAI_API_KEY not set — semantic search unavailable, falling back to keyword-only')
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f'{api_base}/embeddings',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': model,
                    'input': text[:8000],
                }
            )
            response.raise_for_status()
            return response.json()['data'][0]['embedding']
    except Exception as e:
        logger.warning('Embedding failed (%s). Falling back to keyword-only search.', e)
        return None

# Zikra MCP Router — n8n Workflow

This folder holds the n8n workflow JSON that powers the Zikra webhook.

## Export from your instance

1. Go to your n8n instance
2. Open the **Zikra MCP Router** workflow  
3. Click the 3-dot menu (top right) → **Download**
4. Save the file here as `zikra_mcp_router.json`

## Import to a new instance

1. Go to your n8n instance
2. Workflows → **Import from file**
3. Select `zikra_mcp_router.json`
4. Set your credentials (PostgreSQL, OpenAI)
5. Click **Activate**

## Workflow ID (veltisai production)

`2Hz5Q88xRttYZU0X`

Use the n8n export API if you have admin access:
```bash
curl -s "https://your-n8n-domain/api/v1/workflows/2Hz5Q88xRttYZU0X" \
  -H "X-N8N-API-KEY: your-api-key" \
  > zikra_mcp_router.json
```

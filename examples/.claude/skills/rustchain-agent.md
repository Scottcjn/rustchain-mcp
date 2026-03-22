# RustChain Agent Skill

This skill enables Claude to interact with the RustChain blockchain and BoTTube video platform using the RustChain MCP server.

## Setup Instructions

1. Install the MCP server:
   ```bash
   pip install rustchain-mcp
   ```

2. Configure Claude Desktop (in `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):
   ```json
   {
     "mcpServers": {
       "rustchain": {
         "command": "rustchain-mcp",
         "args": []
       }
     }
   }
   ```

3. Reload Claude Desktop.

## Usage

You can now ask Claude to:
- "Check the balance of wallet address XYZ"
- "List the top active miners"
- "Find open bounties with rewards over 100 RTC"
- "Search for BoTTube videos about AI"

## Example Prompts

```text
// Find high-value bounties
"Can you check the RustChain network for any open bounties offering more than 50 RTC?"

// Check wallet balance
"What is the current balance of wallet address w_123456789?"

// View miners
"Show me the top 5 active miners and their hardware architectures."
```

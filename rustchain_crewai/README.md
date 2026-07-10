# RustChain CrewAI Tools

Native RustChain tools for [CrewAI](https://github.com/crewAIInc/crewAI) agents.

## Installation

```bash
pip install crewai requests
```

## Available Tools

| Tool | Description |
|------|-------------|
| `RustChainCheckBalance` | Check RTC token balance for a wallet |
| `RustChainListBounties` | List available bounties for earning RTC |
| `RustChainGetNodeHealth` | Check RustChain node health status |
| `RustChainGetCurrentEpoch` | Get current epoch information |
| `RustChainGetMiners` | List active miners with hardware types |
| `RustChainBoTTubeSearch` | Search BoTTube AI video platform |
| `RustChainBoTTubeStats` | Get BoTTube platform statistics |
| `RustChainBeaconDiscover` | Discover AI agents on Beacon network |
| `RustChainBeaconNetworkStats` | Get Beacon network statistics |
| `RustChainBeaconChat` | Chat with native Beacon agents |

## Usage

```python
from crewai import Agent, Task, Crew
from rustchain_crewai import (
    RustChainCheckBalance,
    RustChainListBounties,
    RustChainGetNodeHealth,
    RustChainGetCurrentEpoch,
)

# Create an agent with RustChain tools
analyst = Agent(
    role="Blockchain Analyst",
    goal="Analyze RustChain blockchain data and provide insights",
    tools=[
        RustChainCheckBalance(),
        RustChainListBounties(),
        RustChainGetNodeHealth(),
        RustChainGetCurrentEpoch(),
    ],
    verbose=True,
)

# Create a task
task = Task(
    description="Check the current RustChain node health and epoch information",
    agent=analyst,
)

# Run the crew
crew = Crew(agents=[analyst], tasks=[task])
result = crew.kickoff()
print(result)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RUSTCHAIN_NODE` | `https://50.28.86.131` | RustChain node URL |
| `BOTTUBE_URL` | `https://bottube.ai` | BoTTube platform URL |
| `BEACON_URL` | `https://rustchain.org/beacon` | Beacon network URL |
| `TLS_VERIFY` | `0` | Set to `1` to verify TLS certificates |

## API Reference

### RustChainCheckBalance

Check RTC token balance for a RustChain wallet.

```python
tool = RustChainCheckBalance()
result = tool._run(wallet_id="dual-g4-125")
# Output: "Wallet dual-g4-125: 100.5 RTC ($10.05 USD reference)"
```

### RustChainListBounties

List available RustChain bounties for earning RTC tokens.

```python
tool = RustChainListBounties()
result = tool._run()
# Output: Bounty program information
```

### RustChainGetNodeHealth

Check RustChain node health status.

```python
tool = RustChainGetNodeHealth()
result = tool._run()
# Output: "RustChain Node: Healthy\nVersion: 1.0.0\n..."
```

### RustChainGetCurrentEpoch

Get current RustChain epoch information.

```python
tool = RustChainGetCurrentEpoch()
result = tool._run()
# Output: "Epoch: 42\nSlot: 1234\n..."
```

## License

MIT License - see [LICENSE](../LICENSE) for details.

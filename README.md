# Amazon Connect MCP Tools

Create and attach Lambda-powered tools (MCP tools) to Amazon Connect AI Agents.

## What It Does

This skill enables you to add custom tools to Amazon Connect's ORCHESTRATION AI Agents. The tools are implemented as Flow Modules that invoke Lambda functions, allowing your AI agent to:

- Call external APIs during conversations
- Perform database lookups
- Execute custom business logic
- Integrate with any AWS service

## Architecture

```
Caller → Connect Flow → AI Agent (ORCHESTRATION)
                              ↓
                        MCP Tool Decision
                              ↓
                      Flow Module (Lambda)
                              ↓
                        Lambda Function
                              ↓
                      Response to Agent
```

## Key Features

- **Direct API Integration**: Uses direct AWS API calls to work around boto3 limitations with `ExternalInvocationConfiguration`
- **Security Profile Setup**: Includes steps to configure proper permissions for AI agents
- **Complete Workflow**: 8-step process from Lambda permission to published agent
- **Error Handling**: Documented common errors and solutions

## Quick Start

1. Create a Lambda function that handles your tool logic
2. Follow the 8 steps in SKILL.md:
   - Add Lambda permission for Connect
   - Create Flow Module (requires direct API, not boto3!)
   - Create Flow Module Version
   - Attach tool to Agent (save only)
   - Enable Module in Security Profile
   - Attach Security Profile to Agent
   - Publish Agent

## Important Discoveries

This skill documents several undocumented AWS behaviors:

| Issue | Solution |
|-------|----------|
| boto3 doesn't support `ExternalInvocationConfiguration` | Use direct REST API with SigV4 auth |
| toolName must start with a letter | Prefix with `tool_` |
| Flow Module content format | Use `EndFlowModuleExecution`, not `FlowModuleReturn` |
| Security profile requires two steps | Enable module + attach profile to agent |

## Requirements

- Amazon Connect instance with Q in Connect enabled
- boto3
- requests (for direct API calls)
- AWS credentials with Connect and Lambda permissions

## Files

- `SKILL.md` - Complete instructions and code samples
- `scripts/` - Helper scripts (needs updating to use direct API)
- `references/` - Additional documentation
- `evals/` - Test cases

## License

MIT

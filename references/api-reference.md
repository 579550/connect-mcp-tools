# API Reference

## Critical Format Discoveries

### toolId Format
```
aws_custom_flows__<flow-module-uuid>_<version-number>
```

Example: `aws_custom_flows__85e9e0a8-12ca-49a6-ae32-b326d554066e_2`

### toolName Format
UUID with first 2 characters removed, hyphens replaced with underscores.

```python
def make_tool_name(uuid):
    return uuid[2:].replace('-', '_')
```

Example: `85e9e0a8-12ca-49a6-ae32-b326d554066e` → `e9e0a8_12ca_49a6_ae32_b326d554066e`

### Built-in Tool Formats
- Knowledge Base Retrieve: `aws_service__qconnect_Retrieve`

## Tool Types

| Type | Use Case | Required Fields |
|------|----------|-----------------|
| `MODEL_CONTEXT_PROTOCOL` | Lambda/Flow Module invocation | toolName, toolType, toolId |
| `RETURN_TO_CONTROL` | Complete/Escalate actions | toolName, toolType, description, instruction, inputSchema |
| `CONSTANT` | Static responses (testing) | toolName, toolType, constantToolConfiguration |

## MCP Tool Configuration

### Minimal (Recommended)
```python
{
    'toolName': 'e9e0a8_12ca_49a6_ae32_b326d554066e',
    'toolType': 'MODEL_CONTEXT_PROTOCOL',
    'toolId': 'aws_custom_flows__85e9e0a8-12ca-49a6-ae32-b326d554066e_2'
}
```

**DO NOT include** description, inputSchema, or instruction - these are inherited from the Flow Module and cause validation errors if overridden.

### RETURN_TO_CONTROL Configuration
```python
{
    'toolName': 'Complete',
    'toolType': 'RETURN_TO_CONTROL',
    'description': 'Complete the conversation',
    'instruction': {
        'instruction': 'Use when customer is satisfied.'
    },
    'inputSchema': {
        'type': 'object',
        'properties': {
            'reason': {'type': 'string', 'description': 'Reason'}
        },
        'required': ['reason']
    }
}
```

## Flow Module Content Schema

```json
{
    "Version": "2019-10-30",
    "StartAction": "entry",
    "Actions": [...],
    "Settings": {
        "InputParameters": [],
        "OutputParameters": [],
        "ExternalInvocationConfiguration": {
            "Enabled": true
        }
    }
}
```

**ExternalInvocationConfiguration.Enabled: true** is REQUIRED for MCP tools.

## Security Profile Flow Modules

### Add Permission
```python
connect.update_security_profile(
    InstanceId='INSTANCE_ID',
    SecurityProfileId='PROFILE_ID',
    AllowedFlowModules=[
        {'FlowModuleId': 'MODULE_UUID'}
    ]
)
```

### Check Permissions
```python
connect.list_security_profile_flow_modules(
    InstanceId='INSTANCE_ID',
    SecurityProfileId='PROFILE_ID'
)
```

## Common Validation Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `MCP tool not found` | Invalid toolId format | Use `aws_custom_flows__UUID_VERSION` |
| `does not allow overriding description` | Adding description to MCP tool config | Remove description field |
| `does not allow overriding input schema` | Adding inputSchema to MCP tool config | Remove inputSchema field |
| `Tool name contains invalid characters` | toolName doesn't start with letter | Strip first 2 chars of UUID |
| `missing required variable: inputSchema` | RETURN_TO_CONTROL without inputSchema | Add inputSchema with properties |

## Version and Alias Management

### Create Version
```python
connect.create_contact_flow_module_version(
    InstanceId='INSTANCE_ID',
    ContactFlowModuleId='MODULE_ID'
)
# Returns: {'Version': 1, ...}
```

### Create Alias
```python
connect.create_contact_flow_module_alias(
    InstanceId='INSTANCE_ID',
    ContactFlowModuleId='MODULE_ID',
    Name='prod',
    Description='Production alias',
    ContactFlowModuleVersion=1  # Integer, not string!
)
```

### Update Alias to New Version
```python
connect.update_contact_flow_module_alias(
    InstanceId='INSTANCE_ID',
    ContactFlowModuleId='MODULE_ID',
    AliasId='ALIAS_ID',  # Not ContactFlowModuleAliasId!
    ContactFlowModuleVersion=2  # Integer!
)
```

## SDK Requirements

- **boto3 >= 1.42.0** required for ORCHESTRATION agent support
- Older versions only support: MANUAL_SEARCH, ANSWER_RECOMMENDATION, SELF_SERVICE
- AWS CLI does not yet support ORCHESTRATION type (use boto3)

## Finding Resources

```python
# List assistants
qconnect.list_assistants()

# List agents
qconnect.list_ai_agents(assistantId=ASSISTANT_ID)

# List ORCHESTRATION prompts
prompts = qconnect.list_ai_prompts(assistantId=ASSISTANT_ID)
for p in prompts['aiPromptSummaries']:
    if p['type'] == 'ORCHESTRATION':
        print(f"{p['aiPromptId']}:$LATEST")

# List flow modules
connect.list_contact_flow_modules(InstanceId=INSTANCE_ID)
```

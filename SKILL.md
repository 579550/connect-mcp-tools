---
name: connect-mcp-tools
description: Add Lambda-powered tools (MCP tools) to Amazon Connect AI Agents. Use this skill when users want to create Flow Modules as tools, attach tools to Connect ORCHESTRATION agents, add Lambda functions as AI agent capabilities, or build conversational AI with custom tool invocations. Works for any Connect instance - customer service bots, IVR automation, helpdesk agents, or any voice/chat AI that needs to call backend services.
---

# Amazon Connect MCP Tools Skill

Create and attach Flow Module tools to Amazon Connect ORCHESTRATION AI Agents. This enables your AI agent to invoke Lambda functions as tools during conversations.

## Overview

Amazon Connect's AI Agents (introduced re:Invent 2025) support **Model Context Protocol (MCP) tools** that allow the agent to call external services. Flow Modules serve as the bridge between the AI agent and your Lambda functions.

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

## Prerequisites
1. An Amazon Connect instance with Q in Connect enabled
2. A Lambda function that handles the tool logic
3. boto3 installed
4. `requests` package installed (for direct API calls - boto3 doesn't support all features)

## Complete Workflow

The full sequence to create a working MCP tool:

1. Add Lambda permission for Connect
2. Create Flow Module with ExternalInvocationConfiguration (requires direct API)
3. Create Flow Module Version
4. Attach tool to Agent (save, don't publish yet)
5. Enable Module in Security Profile
6. Attach Security Profile to Agent
7. Publish Agent

### Step 1: Add Lambda Permission

```python
import boto3

lambda_client = boto3.client('lambda', region_name=REGION)

lambda_client.add_permission(
    FunctionName='YourLambdaFunction',
    StatementId='AllowConnect',
    Action='lambda:InvokeFunction',
    Principal='connect.amazonaws.com',
    SourceArn=f'arn:aws:connect:{REGION}:{ACCOUNT}:instance/{INSTANCE_ID}',
    SourceAccount=ACCOUNT
)
```

### Step 2: Create Flow Module (Direct API Required!)

**IMPORTANT**: boto3's `create_contact_flow_module()` does NOT support `ExternalInvocationConfiguration`. You MUST use a direct API call:

```python
import boto3
import json
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

session = boto3.Session(region_name=REGION)
credentials = session.get_credentials()

# Flow content - use this exact structure
content = {
    "Version": "2019-10-30",
    "StartAction": "InvokeLambda",
    "Metadata": {
        "entryPointPosition": {"x": 40, "y": 520},
        "ActionMetadata": {
            "EndModule": {"position": {"x": 0, "y": 0}},
            "InvokeLambda": {
                "position": {"x": 0, "y": 260},
                "parameters": {"LambdaFunctionARN": {"displayName": LAMBDA_ARN}},
                "dynamicMetadata": {}
            }
        },
        "Annotations": []
    },
    "Actions": [
        {"Parameters": {}, "Identifier": "EndModule", "Type": "EndFlowModuleExecution", "Transitions": {}},
        {
            "Parameters": {
                "LambdaFunctionARN": LAMBDA_ARN,
                "InvocationTimeLimitSeconds": "8",
                "ResponseValidation": {"ResponseType": "JSON"}
            },
            "Identifier": "InvokeLambda",
            "Type": "InvokeLambdaFunction",
            "Transitions": {
                "NextAction": "EndModule",
                "Errors": [{"NextAction": "EndModule", "ErrorType": "NoMatchingError"}]
            }
        }
    ],
    "Settings": {
        "InputParameters": [],
        "OutputParameters": [],
        "Transitions": [
            {"DisplayName": "Success", "ReferenceName": "Success", "Description": ""},
            {"DisplayName": "Error", "ReferenceName": "Error", "Description": ""}
        ]
    }
}

# Direct API call (PUT to create)
endpoint = f"https://connect.{REGION}.amazonaws.com/contact-flow-modules/{INSTANCE_ID}"

body = json.dumps({
    'Name': f'MCP-Tool-{TOOL_NAME}',
    'Description': TOOL_DESCRIPTION,  # This is what the AI sees!
    'Content': json.dumps(content),
    'Settings': json.dumps({
        "input": {"schema": {"type": "object", "properties": {}}},
        "resultData": {"schema": {"type": "object", "properties": {}}},
        "transitions": {"results": []}
    }),
    'ExternalInvocationConfiguration': {'Enabled': True}  # CRITICAL!
})

request = AWSRequest(method='PUT', url=endpoint, data=body, headers={'Content-Type': 'application/json'})
SigV4Auth(credentials, 'connect', REGION).add_auth(request)
response = requests.put(endpoint, headers=dict(request.headers), data=body)
response.raise_for_status()
MODULE_ID = response.json()['Id']
```

### Step 3: Create Version

```python
connect = boto3.client('connect', region_name=REGION)

version_resp = connect.create_contact_flow_module_version(
    InstanceId=INSTANCE_ID,
    ContactFlowModuleId=MODULE_ID
)
VERSION = version_resp['Version']  # int
```

### Step 4: Build Tool Identifiers

```python
# toolId format
tool_id = f"aws_custom_flows__{MODULE_ID}_{VERSION}"

# toolName MUST start with a letter!
tool_name = 'tool_' + MODULE_ID.replace('-', '_')
```

### Step 5: Attach Tool to Agent

**IMPORTANT**: Save only (don't publish yet) - security profile must be configured first!

```python
qconnect = boto3.client('qconnect', region_name=REGION)

# Get existing agent config
agent = qconnect.get_ai_agent(assistantId=ASSISTANT_ID, aiAgentId=AGENT_ID)
config = agent['aiAgent']['configuration']['orchestrationAIAgentConfiguration']

# Clean existing MCP tools (remove fields that cause errors)
def clean_tool(t):
    if t['toolType'] == 'MODEL_CONTEXT_PROTOCOL':
        return {'toolName': t['toolName'], 'toolType': t['toolType'], 'toolId': t['toolId']}
    return t

tools = [clean_tool(t) for t in config.get('toolConfigurations', [])]
tools.append({'toolName': tool_name, 'toolType': 'MODEL_CONTEXT_PROTOCOL', 'toolId': tool_id})

# Save (don't publish yet - need security profile first)
qconnect.update_ai_agent(
    assistantId=ASSISTANT_ID,
    aiAgentId=AGENT_ID,
    configuration={
        'orchestrationAIAgentConfiguration': {
            'orchestrationAIPromptId': config['orchestrationAIPromptId'],
            'connectInstanceArn': config['connectInstanceArn'],
            'toolConfigurations': tools
        }
    },
    visibilityStatus='SAVED'
)
```

### Step 6: Enable Module in Security Profile

```python
connect.update_security_profile(
    InstanceId=INSTANCE_ID,
    SecurityProfileId=SECURITY_PROFILE_ID,
    AllowedFlowModules=[{'FlowModuleId': MODULE_ID}]
)

# Verify
modules = connect.list_security_profile_flow_modules(
    InstanceId=INSTANCE_ID,
    SecurityProfileId=SECURITY_PROFILE_ID
)
print(f"Modules enabled: {[m['FlowModuleId'] for m in modules['AllowedFlowModules']]}")
```

### Step 7: Attach Security Profile to Agent

```python
agent_arn = agent['aiAgent']['aiAgentArn']  # includes :$LATEST

connect.associate_security_profiles(
    InstanceId=INSTANCE_ID,
    EntityType='AI_AGENT',
    EntityArn=agent_arn,
    SecurityProfiles=[{'Id': SECURITY_PROFILE_ID}]
)

# Verify
profiles = connect.list_entity_security_profiles(
    InstanceId=INSTANCE_ID,
    EntityType='AI_AGENT',
    EntityArn=agent_arn
)
print(f"Profiles: {[p['Id'] for p in profiles['SecurityProfiles']]}")
```

### Step 8: Publish Agent

Only publish after security profile is attached:

```python
qconnect.update_ai_agent(
    assistantId=ASSISTANT_ID,
    aiAgentId=AGENT_ID,
    configuration={
        'orchestrationAIAgentConfiguration': {
            'orchestrationAIPromptId': config['orchestrationAIPromptId'],
            'connectInstanceArn': config['connectInstanceArn'],
            'toolConfigurations': tools
        }
    },
    visibilityStatus='PUBLISHED'
)
```

## Important Notes

### Security Profile Requirements

Two things are needed for an AI Agent to invoke a Flow Module:

1. **Permission** - The security profile needs `ContactFlowModules.Execute` permission (Admin has this by default)
2. **AllowedFlowModules** - The specific modules must be listed via `update_security_profile(AllowedFlowModules=[...])`

### Tool Description is Critical
The Flow Module's `Description` field becomes the AI agent's instruction for when to use the tool. Make it detailed:

```
Check Refund Status Tool

Use this tool when a customer asks about their refund status, where their refund is, or when they will receive their refund.

Input: ssn (last 4 digits), tax_year
Output: refund_status, refund_amount, expected_date
```

### Lambda Response Format
Your Lambda should return JSON that the AI can interpret:

```python
def lambda_handler(event, context):
    # Parameters come directly in event
    param1 = event.get('param1')
    
    return {
        'statusCode': 200,
        'result': 'your result here'
    }
```

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `MCP tool not found` | ExternalInvocationConfiguration not enabled | Use direct API to create module |
| `Tool name invalid characters` | toolName starts with number | Prefix with `tool_` |
| `Insufficient permissions` in Console | Security profile not attached or module not allowed | Run steps 6 & 7 |
| `does not allow overriding description` | Adding description to MCP tool config | Only use toolName, toolType, toolId |
| `InvalidContactFlowModuleException` | Wrong flow content structure | Use exact format in Step 2 (StartAction: action name, EndFlowModuleExecution type) |
| `Missing required parameter: AliasName` | Using `Name` instead of `AliasName` for alias | Use `AliasName` param and `ContactFlowModuleVersion` as int |

## Optional: Create Alias

Aliases are optional but useful for version management:

```python
connect.create_contact_flow_module_alias(
    InstanceId=INSTANCE_ID,
    ContactFlowModuleId=MODULE_ID,
    AliasName='prod',  # NOT "Name"!
    Description='Production alias',
    ContactFlowModuleVersion=VERSION  # int, not str!
)
```

## Reference: Finding Resources

```python
# List Connect instances
connect.list_instances()

# List Q Connect assistants  
qconnect.list_assistants()

# List AI agents
qconnect.list_ai_agents(assistantId=ASSISTANT_ID)

# List Flow Modules
connect.list_contact_flow_modules(InstanceId=INSTANCE_ID)

# List Security Profiles
connect.list_security_profiles(InstanceId=INSTANCE_ID)
```

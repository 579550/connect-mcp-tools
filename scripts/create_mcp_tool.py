#!/usr/bin/env python3
"""
Amazon Connect MCP Tool Creator

Creates a Flow Module and attaches it as an MCP tool to an ORCHESTRATION AI Agent.

Usage (with args):
    python create_mcp_tool.py --region us-east-1 --instance-id UUID --lambda-arn ARN \
        --tool-name CheckRefund --tool-description "Check refund status" \
        --assistant-id UUID [--agent-id UUID | --create-agent]

Usage (interactive):
    python create_mcp_tool.py --interactive
"""

import boto3
import json
import argparse
import sys
import os
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def make_tool_id(module_uuid: str, version: int) -> str:
    """Generate toolId for Flow Module MCP tool."""
    return f"aws_custom_flows__{module_uuid}_{version}"


def make_tool_name(name: str, module_uuid: str = None) -> str:
    """Generate toolName for Flow Module MCP tool.
    
    Uses the provided name (sanitized) instead of UUID for readability.
    Falls back to UUID-based name if no name provided.
    """
    if name:
        # Sanitize: lowercase, replace spaces/hyphens with underscores, prefix with 'tool_'
        sanitized = name.lower().replace('-', '_').replace(' ', '_')
        # Ensure it starts with a letter
        if not sanitized[0].isalpha():
            sanitized = 'tool_' + sanitized
        return sanitized
    elif module_uuid:
        return 'tool_' + module_uuid.replace('-', '_')
    else:
        raise ValueError("Either name or module_uuid must be provided")


def test_lambda(lambda_client, lambda_arn: str, test_params: dict = None) -> dict:
    """Test a Lambda function and return its input/output schema.
    
    Returns dict with:
        - input_params: list of parameter names the Lambda expects
        - output_fields: list of output field names from result (NOT statusCode!)
        - sample_response: the full Lambda response for inspection
    """
    import json
    
    payload = {
        'Details': {
            'Parameters': test_params or {}
        }
    }
    
    response = lambda_client.invoke(
        FunctionName=lambda_arn,
        InvocationType='RequestResponse',
        Payload=json.dumps(payload)
    )
    
    result = json.loads(response['Payload'].read())
    
    # Extract output fields from 'result' key (NOT statusCode!)
    output_fields = []
    if isinstance(result.get('result'), dict):
        output_fields = list(result['result'].keys())
    
    return {
        'input_params': list((test_params or {}).keys()),
        'output_fields': output_fields,
        'sample_response': result
    }


def prompt_user(prompt: str, default: str = None, required: bool = True) -> str:
    """Prompt user for input with optional default."""
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    else:
        while True:
            user_input = input(f"{prompt}: ").strip()
            if user_input or not required:
                return user_input
            print("  This field is required. Please enter a value.")


def discover_resources(region: str) -> dict:
    """Discover available Connect resources in the region."""
    connect = boto3.client('connect', region_name=region)
    qconnect = boto3.client('qconnect', region_name=region)
    
    resources = {'instances': [], 'assistants': [], 'agents': [], 'lambdas': []}
    
    # List Connect instances
    try:
        instances = connect.list_instances()
        for inst in instances.get('InstanceSummaryList', []):
            resources['instances'].append({
                'id': inst['Id'],
                'name': inst.get('InstanceAlias', inst['Id'])
            })
    except Exception as e:
        print(f"  Warning: Could not list instances: {e}")
    
    # List Q Connect assistants
    try:
        assistants = qconnect.list_assistants()
        for asst in assistants.get('assistantSummaries', []):
            resources['assistants'].append({
                'id': asst['assistantId'],
                'name': asst.get('name', asst['assistantId'])
            })
    except Exception as e:
        print(f"  Warning: Could not list assistants: {e}")
    
    # List Lambda functions
    try:
        lambda_client = boto3.client('lambda', region_name=region)
        functions = lambda_client.list_functions()
        for fn in functions.get('Functions', []):
            resources['lambdas'].append({
                'arn': fn['FunctionArn'],
                'name': fn['FunctionName']
            })
    except Exception as e:
        print(f"  Warning: Could not list Lambda functions: {e}")
    
    return resources


def interactive_mode() -> dict:
    """Run interactive mode to gather user inputs."""
    print("\n" + "="*60)
    print("  Amazon Connect MCP Tool Creator - Interactive Mode")
    print("="*60 + "\n")
    
    # Region
    region = prompt_user("AWS Region", default=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'))
    
    print(f"\nDiscovering resources in {region}...")
    resources = discover_resources(region)
    
    # Instance selection
    if resources['instances']:
        print("\nAvailable Connect Instances:")
        for i, inst in enumerate(resources['instances'], 1):
            print(f"  {i}. {inst['name']} ({inst['id']})")
        choice = prompt_user("Select instance number or enter ID", default="1")
        if choice.isdigit() and int(choice) <= len(resources['instances']):
            instance_id = resources['instances'][int(choice)-1]['id']
        else:
            instance_id = choice
    else:
        instance_id = prompt_user("Connect Instance ID")
    
    # Assistant selection
    if resources['assistants']:
        print("\nAvailable Q Connect Assistants:")
        for i, asst in enumerate(resources['assistants'], 1):
            print(f"  {i}. {asst['name']} ({asst['id']})")
        choice = prompt_user("Select assistant number or enter ID", default="1")
        if choice.isdigit() and int(choice) <= len(resources['assistants']):
            assistant_id = resources['assistants'][int(choice)-1]['id']
        else:
            assistant_id = choice
    else:
        assistant_id = prompt_user("Q Connect Assistant ID")
    
    # Lambda selection
    if resources['lambdas']:
        print("\nAvailable Lambda Functions:")
        for i, fn in enumerate(resources['lambdas'][:20], 1):  # Show first 20
            print(f"  {i}. {fn['name']}")
        if len(resources['lambdas']) > 20:
            print(f"  ... and {len(resources['lambdas'])-20} more")
        choice = prompt_user("Select Lambda number or enter ARN")
        if choice.isdigit() and int(choice) <= len(resources['lambdas']):
            lambda_arn = resources['lambdas'][int(choice)-1]['arn']
        else:
            lambda_arn = choice
    else:
        lambda_arn = prompt_user("Lambda Function ARN")
    
    # Test Lambda to discover schema
    print("\n--- Lambda Schema Discovery ---")
    print("Testing Lambda to discover input/output schema...")
    
    lambda_client = boto3.client('lambda', region_name=region)
    input_params = []
    output_fields = []
    
    # Ask for input parameters
    print("\nInput Parameters:")
    print("  Enter the parameter names your Lambda expects (comma-separated)")
    print("  Example: order_id, customer_name, date")
    input_str = prompt_user("Input parameters", required=False)
    if input_str:
        input_params = [p.strip() for p in input_str.split(',') if p.strip()]
    
    # Test Lambda with provided params
    if input_params:
        try:
            test_params = {p: 'test_value' for p in input_params}
            lambda_result = test_lambda(lambda_client, lambda_arn, test_params)
            if lambda_result['output_fields']:
                output_fields = lambda_result['output_fields']
                print(f"\n  ✓ Discovered output fields from Lambda: {output_fields}")
                print(f"    Sample response: {json.dumps(lambda_result['sample_response'], indent=2)[:500]}")
        except Exception as e:
            print(f"\n  Warning: Lambda test failed: {e}")
    
    # Ask for output fields if not discovered
    if not output_fields:
        print("\nOutput Fields:")
        print("  Enter the field names from Lambda's 'result' object (comma-separated)")
        print("  DO NOT include 'statusCode' - only fields inside 'result'")
        print("  Example: status, amount, date, items")
        output_str = prompt_user("Output fields", required=False)
        if output_str:
            output_fields = [f.strip() for f in output_str.split(',') if f.strip()]
    
    # Tool details
    print("\n--- Tool Configuration ---")
    tool_name = prompt_user("Tool Name (e.g., check-order, get-refund-status)")
    
    print("\nTool Description - This is what the AI sees to decide when to use the tool.")
    print("Include: what it does, when to use it, expected inputs/outputs.")
    print("Example: 'Check order status. Use when customer asks about their order,")
    print("         shipping, or delivery. Input: order_id. Output: status, location.'")
    tool_description = prompt_user("Tool Description")
    
    # Agent configuration
    print("\n--- Agent Configuration ---")
    print("1. Create a new ORCHESTRATION agent")
    print("2. Add tool to existing agent")
    agent_choice = prompt_user("Choose option", default="1")
    
    create_agent = agent_choice == "1"
    agent_id = None
    agent_name = None
    
    if create_agent:
        agent_name = prompt_user("New Agent Name", default=f"{tool_name}-Agent")
    else:
        # List existing agents
        try:
            qconnect = boto3.client('qconnect', region_name=region)
            agents = qconnect.list_ai_agents(assistantId=assistant_id)
            orch_agents = [a for a in agents.get('aiAgentSummaries', []) 
                          if a.get('type') == 'ORCHESTRATION']
            if orch_agents:
                print("\nExisting ORCHESTRATION Agents:")
                for i, agent in enumerate(orch_agents, 1):
                    print(f"  {i}. {agent.get('name', 'Unnamed')} ({agent['aiAgentId']})")
                choice = prompt_user("Select agent number or enter ID")
                if choice.isdigit() and int(choice) <= len(orch_agents):
                    agent_id = orch_agents[int(choice)-1]['aiAgentId']
                else:
                    agent_id = choice
            else:
                agent_id = prompt_user("Agent ID")
        except:
            agent_id = prompt_user("Agent ID")
    
    return {
        'region': region,
        'instance_id': instance_id,
        'assistant_id': assistant_id,
        'lambda_arn': lambda_arn,
        'tool_name': tool_name,
        'tool_description': tool_description,
        'create_agent': create_agent,
        'agent_id': agent_id,
        'agent_name': agent_name or f"{tool_name}-Agent",
        'security_profile_id': None,  # Will auto-detect Admin
        'input_params': input_params,
        'output_fields': output_fields
    }


def create_flow_module_direct(region: str, instance_id: str, name: str, description: str, 
                               lambda_arn: str, input_params: list, output_fields: list) -> str:
    """Create a Flow Module using direct API with proper input/output mapping.
    
    Args:
        region: AWS region
        instance_id: Connect instance ID
        name: Human-readable tool name (e.g., "check-date")
        description: Tool description for AI agent
        lambda_arn: Lambda function ARN
        input_params: List of input parameter names (from Lambda test)
        output_fields: List of output field names from result (NOT statusCode!)
    
    Returns:
        Module ID
    """
    session = boto3.Session(region_name=region)
    credentials = session.get_credentials()
    
    # Build input schema (ALL types must be "string"!)
    input_schema = {
        "type": "object",
        "properties": {p: {"type": "string"} for p in input_params}
    }
    
    # Build output schema (ALL types must be "string" - Connect limitation!)
    # NEVER include statusCode!
    output_schema = {
        "type": "object",
        "properties": {f: {"type": "string"} for f in output_fields}
    }
    
    # Build LambdaInvocationAttributes with correct path format
    lambda_inputs = {p: f"$.Modules.Input.{p}" for p in input_params}
    
    # Build ResultData with correct path format (reads from $.External.result.X)
    result_data = {f: f"$.External.result.{f}" for f in output_fields}
    
    # Flow content with proper input/output mapping
    content = {
        "Version": "2019-10-30",
        "StartAction": "InvokeLambda",
        "Metadata": {
            "entryPointPosition": {"x": 40, "y": 520},
            "ActionMetadata": {
                "EndModule": {"position": {"x": 0, "y": 0}},
                "InvokeLambda": {
                    "position": {"x": 0, "y": 260},
                    "parameters": {"LambdaFunctionARN": {"displayName": lambda_arn}},
                    "dynamicMetadata": {p: False for p in input_params}
                }
            },
            "Annotations": []
        },
        "Actions": [
            {
                "Parameters": {"ResultData": result_data} if result_data else {},
                "Identifier": "EndModule",
                "Type": "EndFlowModuleExecution",
                "Transitions": {}
            },
            {
                "Parameters": {
                    "LambdaFunctionARN": lambda_arn,
                    "InvocationTimeLimitSeconds": "8",
                    "ResponseValidation": {"ResponseType": "JSON"},
                    "LambdaInvocationAttributes": lambda_inputs
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
    
    # Settings with schemas (separate from content!)
    settings = {
        "input": {"schema": input_schema},
        "resultData": {"schema": output_schema},
        "transitions": {"results": []}
    }
    
    # Direct API call (PUT to create)
    endpoint = f"https://connect.{region}.amazonaws.com/contact-flow-modules/{instance_id}"
    
    body = json.dumps({
        'Name': name,  # Use descriptive name, not tool_UUID
        'Description': description,
        'Content': json.dumps(content),
        'Settings': json.dumps(settings),
        'ExternalInvocationConfiguration': {'Enabled': True}
    })
    
    request = AWSRequest(method='PUT', url=endpoint, data=body, headers={'Content-Type': 'application/json'})
    SigV4Auth(credentials, 'connect', region).add_auth(request)
    response = requests.put(endpoint, headers=dict(request.headers), data=body)
    response.raise_for_status()
    
    return response.json()['Id']


def update_flow_module_direct(region: str, instance_id: str, module_id: str,
                               input_params: list, output_fields: list, lambda_arn: str) -> None:
    """Update an existing Flow Module's content and schema using direct API.
    
    Args:
        region: AWS region
        instance_id: Connect instance ID
        module_id: Existing module ID
        input_params: List of input parameter names
        output_fields: List of output field names from result (NOT statusCode!)
        lambda_arn: Lambda function ARN
    """
    session = boto3.Session(region_name=region)
    credentials = session.get_credentials()
    
    # Build schemas
    input_schema = {
        "type": "object",
        "properties": {p: {"type": "string"} for p in input_params}
    }
    output_schema = {
        "type": "object",
        "properties": {f: {"type": "string"} for f in output_fields}
    }
    
    lambda_inputs = {p: f"$.Modules.Input.{p}" for p in input_params}
    result_data = {f: f"$.External.result.{f}" for f in output_fields}
    
    content = {
        "Version": "2019-10-30",
        "StartAction": "InvokeLambda",
        "Metadata": {
            "entryPointPosition": {"x": 40, "y": 520},
            "ActionMetadata": {
                "EndModule": {"position": {"x": 0, "y": 0}},
                "InvokeLambda": {
                    "position": {"x": 0, "y": 260},
                    "parameters": {"LambdaFunctionARN": {"displayName": lambda_arn}},
                    "dynamicMetadata": {p: False for p in input_params}
                }
            },
            "Annotations": []
        },
        "Actions": [
            {
                "Parameters": {"ResultData": result_data} if result_data else {},
                "Identifier": "EndModule",
                "Type": "EndFlowModuleExecution",
                "Transitions": {}
            },
            {
                "Parameters": {
                    "LambdaFunctionARN": lambda_arn,
                    "InvocationTimeLimitSeconds": "8",
                    "ResponseValidation": {"ResponseType": "JSON"},
                    "LambdaInvocationAttributes": lambda_inputs
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
    
    settings = {
        "input": {"schema": input_schema},
        "resultData": {"schema": output_schema},
        "transitions": {"results": []}
    }
    
    # UPDATE endpoint (POST, not PUT!)
    endpoint = f"https://connect.{region}.amazonaws.com/contact-flow-modules/{instance_id}/{module_id}/content"
    
    body = json.dumps({
        'Content': json.dumps(content),
        'Settings': json.dumps(settings)
    })
    
    request = AWSRequest(method='POST', url=endpoint, data=body, headers={'Content-Type': 'application/json'})
    SigV4Auth(credentials, 'connect', region).add_auth(request)
    response = requests.post(endpoint, headers=dict(request.headers), data=body)
    response.raise_for_status()


def create_flow_module(connect, instance_id: str, name: str, description: str, lambda_arn: str) -> str:
    """DEPRECATED: Use create_flow_module_direct() instead for proper input/output mapping."""
    print("WARNING: create_flow_module() is deprecated. Use create_flow_module_direct() for proper I/O mapping.")
    
    content = {
        "Version": "2019-10-30",
        "StartAction": "InvokeLambda",
        "Metadata": {
            "entryPointPosition": {"x": 40, "y": 520},
            "ActionMetadata": {
                "EndModule": {"position": {"x": 0, "y": 0}},
                "InvokeLambda": {
                    "position": {"x": 0, "y": 260},
                    "parameters": {"LambdaFunctionARN": {"displayName": lambda_arn}},
                    "dynamicMetadata": {}
                }
            },
            "Annotations": []
        },
        "Actions": [
            {"Parameters": {}, "Identifier": "EndModule", "Type": "EndFlowModuleExecution", "Transitions": {}},
            {
                "Parameters": {
                    "LambdaFunctionARN": lambda_arn,
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
    
    response = connect.create_contact_flow_module(
        InstanceId=instance_id,
        Name=name,
        Description=description,
        Content=json.dumps(content)
    )
    
    return response['Id']


def publish_module(connect, instance_id: str, module_id: str) -> tuple:
    """Create a version and alias for the module. Returns (version, alias_id)."""
    
    # Create version
    version_resp = connect.create_contact_flow_module_version(
        InstanceId=instance_id,
        ContactFlowModuleId=module_id
    )
    version = version_resp['Version']
    
    # Create alias
    alias_resp = connect.create_contact_flow_module_alias(
        InstanceId=instance_id,
        ContactFlowModuleId=module_id,
        Name='prod',
        Description='Production alias',
        ContactFlowModuleVersion=version
    )
    
    return version, alias_resp['Id']


def get_return_to_control_tools():
    """Return the required Complete and Escalate tools."""
    return [
        {
            'toolName': 'Complete',
            'toolType': 'RETURN_TO_CONTROL',
            'description': 'Complete the conversation when customer has no more questions',
            'instruction': {'instruction': 'Mark conversation complete after confirming customer is satisfied.'},
            'inputSchema': {
                'type': 'object',
                'properties': {'reason': {'type': 'string', 'description': 'Reason for completion'}},
                'required': ['reason']
            }
        },
        {
            'toolName': 'Escalate',
            'toolType': 'RETURN_TO_CONTROL',
            'description': 'Escalate to human agent when issue cannot be resolved',
            'instruction': {'instruction': 'Escalate when you cannot adequately assist the customer.'},
            'inputSchema': {
                'type': 'object',
                'properties': {'reason': {'type': 'string', 'description': 'Reason for escalation'}},
                'required': ['reason']
            }
        }
    ]


def get_orchestration_prompt_template(agent_name: str = "Customer Service Agent", 
                                       company_name: str = "our company",
                                       domain_context: str = "") -> str:
    """Generate an ORCHESTRATION prompt template.
    
    Args:
        agent_name: Name/role of the agent
        company_name: Company name to insert
        domain_context: Additional domain-specific instructions
    
    Returns:
        Prompt template string with Handlebars syntax for tools
    """
    return f"""You are a {agent_name} for {company_name}.

## Your Role
- Assist customers with their inquiries professionally and efficiently
- Use available tools to look up information and perform actions
- Always confirm actions before executing them
- Be concise but thorough in your responses

## Available Tools
You have access to the following tools. Use them when appropriate:

{{{{#each tools}}}}
### {{{{toolName}}}}
{{{{description}}}}
{{{{/each}}}}

{domain_context}

## Guidelines
1. **Greet** the customer warmly
2. **Listen** to understand their needs  
3. **Use tools** to gather information or perform actions
4. **Confirm** before making changes
5. **Summarize** what was done
6. **Ask** if there's anything else

## Important Rules
- Never share sensitive internal information
- If unsure, escalate to a human agent using the Escalate tool
- Always verify customer identity before account changes
- Use Complete tool when the customer is satisfied and has no more questions

## Response Format
- Keep responses conversational and natural
- Use bullet points for lists when helpful
- Confirm understanding before taking action
- Be empathetic and patient
"""


def create_orchestration_prompt(qconnect, assistant_id: str, prompt_name: str,
                                 prompt_text: str) -> str:
    """Create an ORCHESTRATION prompt and return the prompt ID.
    
    Args:
        qconnect: QConnect client
        assistant_id: Q Connect Assistant ID
        prompt_name: Name for the prompt
        prompt_text: The prompt template text
    
    Returns:
        Prompt ID in format "uuid:$LATEST"
    """
    response = qconnect.create_ai_prompt(
        assistantId=assistant_id,
        name=prompt_name,
        description=f'ORCHESTRATION prompt for {prompt_name}',
        type='ORCHESTRATION',
        templateType='TEXT',
        templateConfiguration={
            'textFullAIPromptEditTemplateConfiguration': {
                'text': prompt_text
            }
        },
        visibilityStatus='PUBLISHED'
    )
    return f"{response['aiPrompt']['aiPromptId']}:$LATEST"


def create_agent_func(qconnect, assistant_id: str, instance_arn: str, agent_name: str, 
                 prompt_id: str, tool_configs: list) -> str:
    """Create a new ORCHESTRATION AI agent."""
    
    response = qconnect.create_ai_agent(
        assistantId=assistant_id,
        name=agent_name,
        description=f'ORCHESTRATION agent with MCP tools - created by connect-mcp-tools',
        type='ORCHESTRATION',
        configuration={
            'orchestrationAIAgentConfiguration': {
                'orchestrationAIPromptId': prompt_id,
                'connectInstanceArn': instance_arn,
                'toolConfigurations': tool_configs
            }
        },
        visibilityStatus='PUBLISHED'
    )
    
    return response['aiAgent']['aiAgentId']


def add_tool_to_agent(qconnect, assistant_id: str, agent_id: str, 
                      instance_arn: str, mcp_tool: dict) -> None:
    """Add an MCP tool to an existing ORCHESTRATION agent."""
    
    # Get current config
    agent = qconnect.get_ai_agent(assistantId=assistant_id, aiAgentId=agent_id)
    config = agent['aiAgent']['configuration']['orchestrationAIAgentConfiguration']
    tools = config.get('toolConfigurations', [])
    
    # Clean existing MCP tools (remove override fields)
    def clean_mcp_tool(t):
        if t['toolType'] == 'MODEL_CONTEXT_PROTOCOL':
            return {'toolName': t['toolName'], 'toolType': t['toolType'], 'toolId': t['toolId']}
        return t
    
    cleaned_tools = [clean_mcp_tool(t) for t in tools]
    
    # Check if tool already exists
    if not any(t['toolName'] == mcp_tool['toolName'] for t in cleaned_tools):
        cleaned_tools.append(mcp_tool)
    
    # Update agent
    qconnect.update_ai_agent(
        assistantId=assistant_id,
        aiAgentId=agent_id,
        configuration={
            'orchestrationAIAgentConfiguration': {
                'orchestrationAIPromptId': config['orchestrationAIPromptId'],
                'connectInstanceArn': config.get('connectInstanceArn', instance_arn),
                'toolConfigurations': cleaned_tools
            }
        },
        visibilityStatus='PUBLISHED'
    )


def add_security_permissions(connect, instance_id: str, security_profile_id: str, 
                             module_id: str) -> None:
    """Add flow module to security profile's allowed list."""
    
    # Get current allowed modules
    current = connect.list_security_profile_flow_modules(
        InstanceId=instance_id,
        SecurityProfileId=security_profile_id
    )
    
    allowed = current.get('AllowedFlowModules', [])
    existing_ids = [m.get('FlowModuleId') for m in allowed]
    
    if module_id not in existing_ids:
        allowed.append({'FlowModuleId': module_id})
        connect.update_security_profile(
            InstanceId=instance_id,
            SecurityProfileId=security_profile_id,
            AllowedFlowModules=allowed
        )


def find_orchestration_prompt(qconnect, assistant_id: str) -> str:
    """Find an ORCHESTRATION type prompt."""
    prompts = qconnect.list_ai_prompts(assistantId=assistant_id)
    for p in prompts.get('aiPromptSummaries', []):
        if p.get('type') == 'ORCHESTRATION':
            return f"{p['aiPromptId']}:$LATEST"
    raise ValueError("No ORCHESTRATION prompt found. Create one in the console first.")


def find_admin_profile(connect, instance_id: str) -> str:
    """Find the Admin security profile."""
    profiles = connect.list_security_profiles(InstanceId=instance_id)
    for p in profiles['SecurityProfileSummaryList']:
        if p['Name'] == 'Admin':
            return p['Id']
    raise ValueError("Admin security profile not found")


def run_tool_creation(config: dict) -> dict:
    """Execute the tool creation workflow. Returns result dict."""
    
    region = config['region']
    instance_id = config['instance_id']
    assistant_id = config['assistant_id']
    lambda_arn = config['lambda_arn']
    tool_name = config['tool_name']
    tool_description = config['tool_description']
    create_agent = config['create_agent']
    agent_id = config.get('agent_id')
    agent_name = config.get('agent_name', f'{tool_name}-Agent')
    security_profile_id = config.get('security_profile_id')
    input_params = config.get('input_params', [])
    output_fields = config.get('output_fields', [])
    
    # Initialize clients
    connect = boto3.client('connect', region_name=region)
    qconnect = boto3.client('qconnect', region_name=region)
    lambda_client = boto3.client('lambda', region_name=region)
    
    # Get account ID for ARN
    sts = boto3.client('sts')
    account_id = sts.get_caller_identity()['Account']
    instance_arn = f"arn:aws:connect:{region}:{account_id}:instance/{instance_id}"
    
    result = {
        'region': region,
        'instance_id': instance_id,
        'tool_name': tool_name
    }
    
    print(f"\nCreating MCP tool: {tool_name}")
    
    # Step 0: Test Lambda to discover input/output schema
    if not input_params or not output_fields:
        print("  [0/6] Testing Lambda to discover schema...")
        try:
            # Build test params from any provided input_params
            test_params = {p: 'test' for p in input_params} if input_params else {}
            lambda_result = test_lambda(lambda_client, lambda_arn, test_params)
            
            if not input_params:
                print("        WARNING: No input params specified. Set them manually if Lambda requires inputs.")
            if lambda_result['output_fields']:
                output_fields = lambda_result['output_fields']
                print(f"        Discovered output fields: {output_fields}")
            else:
                print("        WARNING: Could not discover output fields. Lambda may not return 'result' dict.")
            
            result['lambda_test'] = lambda_result
        except Exception as e:
            print(f"        Lambda test failed: {e}")
            print("        Proceeding without output mapping (module may not work correctly)")
    
    # Step 1: Create Flow Module with proper I/O mapping using direct API
    print("  [1/6] Creating Flow Module (direct API)...")
    module_id = create_flow_module_direct(
        region=region,
        instance_id=instance_id,
        name=tool_name,
        description=tool_description,
        lambda_arn=lambda_arn,
        input_params=input_params,
        output_fields=output_fields
    )
    result['module_id'] = module_id
    result['input_params'] = input_params
    result['output_fields'] = output_fields
    print(f"        Module ID: {module_id}")
    print(f"        Input params: {input_params}")
    print(f"        Output fields: {output_fields}")
    
    # Step 2: Publish (version + alias)
    print("  [2/7] Publishing module...")
    version, alias_id = publish_module(connect, instance_id, module_id)
    result['version'] = version
    result['alias_id'] = alias_id
    print(f"        Version: {version}, Alias: {alias_id}")
    
    # Step 3: Build MCP tool config with readable name
    mcp_tool = {
        'toolName': make_tool_name(tool_name, module_id),  # Use tool_name, not just UUID!
        'toolType': 'MODEL_CONTEXT_PROTOCOL',
        'toolId': make_tool_id(module_id, version)
    }
    result['tool_id'] = mcp_tool['toolId']
    result['tool_name_internal'] = mcp_tool['toolName']
    print(f"  [3/7] MCP Tool Config:")
    print(f"        toolId: {mcp_tool['toolId']}")
    print(f"        toolName: {mcp_tool['toolName']}")
    
    # Step 4: Attach to agent
    if create_agent:
        print("  [4/7] Creating new ORCHESTRATION agent...")
        
        # Try to find existing prompt, or create one
        try:
            prompt_id = find_orchestration_prompt(qconnect, assistant_id)
            print(f"        Using existing prompt: {prompt_id}")
        except ValueError:
            print("        No existing prompt found, creating new one...")
            # Get domain context from config if provided
            domain_context = config.get('domain_context', '')
            company_name = config.get('company_name', 'our company')
            
            prompt_text = get_orchestration_prompt_template(
                agent_name=agent_name,
                company_name=company_name,
                domain_context=domain_context
            )
            prompt_id = create_orchestration_prompt(
                qconnect, assistant_id, 
                f"{agent_name}-prompt",
                prompt_text
            )
            result['prompt_created'] = True
            print(f"        Created prompt: {prompt_id}")
        
        tools = [mcp_tool] + get_return_to_control_tools()
        final_agent_id = create_agent_func(
            qconnect, assistant_id, instance_arn,
            agent_name, prompt_id, tools
        )
        result['agent_id'] = final_agent_id
        result['agent_created'] = True
        result['prompt_id'] = prompt_id
        print(f"        Agent ID: {final_agent_id}")
    else:
        print(f"  [4/7] Adding tool to agent {agent_id}...")
        add_tool_to_agent(qconnect, assistant_id, agent_id, instance_arn, mcp_tool)
        result['agent_id'] = agent_id
        result['agent_created'] = False
        print("        Done")
    
    # Step 5: Add security permissions
    print("  [5/7] Adding security permissions...")
    profile_id = security_profile_id or find_admin_profile(connect, instance_id)
    add_security_permissions(connect, instance_id, profile_id, module_id)
    result['security_profile_id'] = profile_id
    print("        Done")
    
    # Step 6: Add Lambda permission for Connect
    print("  [6/7] Adding Lambda permission for Connect...")
    try:
        lambda_client.add_permission(
            FunctionName=lambda_arn,
            StatementId=f'AllowConnect_{module_id[:8]}',
            Action='lambda:InvokeFunction',
            Principal='connect.amazonaws.com',
            SourceArn=instance_arn,
            SourceAccount=account_id
        )
        print("        Done")
    except lambda_client.exceptions.ResourceConflictException:
        print("        Permission already exists")
    except Exception as e:
        print(f"        Warning: {e}")
    
    print("  [7/7] Complete!")
    
    print("\n" + "="*60)
    print("  ✓ MCP Tool created and attached successfully!")
    print("="*60)
    print(f"\nSummary:")
    print(f"  Tool Name:      {tool_name}")
    print(f"  Module ID:      {module_id}")
    print(f"  Version:        {version}")
    print(f"  toolId:         {mcp_tool['toolId']}")
    print(f"  toolName:       {mcp_tool['toolName']}")
    print(f"  Agent ID:       {result['agent_id']}")
    print(f"  Input params:   {input_params}")
    print(f"  Output fields:  {output_fields}")
    if result.get('agent_created'):
        print(f"  Agent Name:     {agent_name} (newly created)")
    if result.get('prompt_created'):
        print(f"  Prompt:         Created new prompt")
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Create and attach MCP tool to Connect AI Agent')
    parser.add_argument('--interactive', '-i', action='store_true', 
                        help='Run in interactive mode (guided setup)')
    parser.add_argument('--region', help='AWS region')
    parser.add_argument('--instance-id', help='Connect instance ID')
    parser.add_argument('--lambda-arn', help='Lambda function ARN')
    parser.add_argument('--tool-name', help='Tool name (e.g., check-refund)')
    parser.add_argument('--tool-description', help='Tool description for AI')
    parser.add_argument('--assistant-id', help='Q Connect Assistant ID')
    parser.add_argument('--agent-id', help='Existing agent ID to add tool to')
    parser.add_argument('--create-agent', action='store_true', help='Create new agent')
    parser.add_argument('--agent-name', default='MCP-Tool-Agent', help='Name for new agent')
    parser.add_argument('--security-profile-id', help='Security profile ID (defaults to Admin)')
    parser.add_argument('--input-params', help='Comma-separated input parameter names (e.g., date,service_type)')
    parser.add_argument('--output-fields', help='Comma-separated output field names from result (e.g., status,count)')
    parser.add_argument('--company-name', help='Company name for prompt template')
    parser.add_argument('--domain-context', help='Additional domain-specific instructions for prompt')
    parser.add_argument('--output-json', help='Output result as JSON to file')
    
    args = parser.parse_args()
    
    # Interactive mode
    if args.interactive:
        config = interactive_mode()
    else:
        # CLI mode - validate required args
        required = ['region', 'instance_id', 'lambda_arn', 'tool_name', 
                    'tool_description', 'assistant_id']
        missing = [r for r in required if not getattr(args, r.replace('-', '_'), None)]
        
        if missing:
            print(f"Error: Missing required arguments: {', '.join(missing)}")
            print("Use --interactive for guided setup, or provide all required arguments.")
            sys.exit(1)
        
        if not args.agent_id and not args.create_agent:
            print("Error: Must specify --agent-id or --create-agent")
            sys.exit(1)
        
        # Parse input/output params
        input_params = []
        output_fields = []
        if args.input_params:
            input_params = [p.strip() for p in args.input_params.split(',') if p.strip()]
        if args.output_fields:
            output_fields = [f.strip() for f in args.output_fields.split(',') if f.strip()]
        
        config = {
            'region': args.region,
            'instance_id': args.instance_id,
            'lambda_arn': args.lambda_arn,
            'tool_name': args.tool_name,
            'tool_description': args.tool_description,
            'assistant_id': args.assistant_id,
            'agent_id': args.agent_id,
            'create_agent': args.create_agent,
            'agent_name': args.agent_name,
            'security_profile_id': args.security_profile_id,
            'input_params': input_params,
            'output_fields': output_fields,
            'company_name': args.company_name or 'our company',
            'domain_context': args.domain_context or ''
        }
    
    # Confirm before proceeding
    print("\n--- Configuration ---")
    print(f"  Region:        {config['region']}")
    print(f"  Instance:      {config['instance_id']}")
    print(f"  Lambda:        {config['lambda_arn']}")
    print(f"  Tool Name:   {config['tool_name']}")
    print(f"  Agent:       {'Create new' if config['create_agent'] else config.get('agent_id', 'N/A')}")
    
    confirm = input("\nProceed? [Y/n]: ").strip().lower()
    if confirm and confirm != 'y':
        print("Cancelled.")
        sys.exit(0)
    
    # Execute
    try:
        result = run_tool_creation(config)
        
        # Output JSON if requested
        if args.output_json:
            with open(args.output_json, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"\nResult saved to: {args.output_json}")
            
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()

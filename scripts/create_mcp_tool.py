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


def make_tool_id(module_uuid: str, version: int) -> str:
    """Generate toolId for Flow Module MCP tool."""
    return f"aws_custom_flows__{module_uuid}_{version}"


def make_tool_name(module_uuid: str) -> str:
    """Generate toolName for Flow Module MCP tool."""
    return module_uuid[2:].replace('-', '_')


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
    
    # Tool details
    print("\n--- Tool Configuration ---")
    tool_name = prompt_user("Tool Name (e.g., CheckOrderStatus, GetPaymentPlan)")
    
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
        'security_profile_id': None  # Will auto-detect Admin
    }


def create_flow_module(connect, instance_id: str, name: str, description: str, lambda_arn: str) -> str:
    """Create a Flow Module that invokes a Lambda function."""
    
    content = {
        "Version": "2019-10-30",
        "StartAction": "entry",
        "Actions": [
            {
                "Identifier": "entry",
                "Type": "FlowStart",
                "Transitions": {"NextAction": "invoke_lambda"}
            },
            {
                "Identifier": "invoke_lambda",
                "Type": "InvokeLambdaFunction",
                "Parameters": {
                    "LambdaFunctionARN": lambda_arn,
                    "InvocationTimeLimitSeconds": "8",
                    "ResponseValidation": {"ResponseType": "JSON"}
                },
                "Transitions": {
                    "NextAction": "return_success",
                    "Errors": [{"NextAction": "return_error", "ErrorType": "NoMatchingError"}]
                }
            },
            {
                "Identifier": "return_success",
                "Type": "FlowModuleReturn",
                "Parameters": {"Status": {"Value": "Success"}}
            },
            {
                "Identifier": "return_error",
                "Type": "FlowModuleReturn",
                "Parameters": {"Status": {"Value": "Error"}}
            }
        ],
        "Settings": {
            "InputParameters": [],
            "OutputParameters": [],
            "ExternalInvocationConfiguration": {"Enabled": True}
        }
    }
    
    response = connect.create_contact_flow_module(
        InstanceId=instance_id,
        Name=f"tool_module_{name}",
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
    
    # Initialize clients
    connect = boto3.client('connect', region_name=region)
    qconnect = boto3.client('qconnect', region_name=region)
    
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
    
    # Step 1: Create Flow Module
    print("  [1/5] Creating Flow Module...")
    module_id = create_flow_module(
        connect, instance_id, tool_name, 
        tool_description, lambda_arn
    )
    result['module_id'] = module_id
    print(f"        Module ID: {module_id}")
    
    # Step 2: Publish (version + alias)
    print("  [2/5] Publishing module...")
    version, alias_id = publish_module(connect, instance_id, module_id)
    result['version'] = version
    result['alias_id'] = alias_id
    print(f"        Version: {version}, Alias: {alias_id}")
    
    # Step 3: Build MCP tool config
    mcp_tool = {
        'toolName': make_tool_name(module_id),
        'toolType': 'MODEL_CONTEXT_PROTOCOL',
        'toolId': make_tool_id(module_id, version)
    }
    result['tool_id'] = mcp_tool['toolId']
    result['tool_name_internal'] = mcp_tool['toolName']
    print(f"  [3/5] MCP Tool Config:")
    print(f"        toolId: {mcp_tool['toolId']}")
    print(f"        toolName: {mcp_tool['toolName']}")
    
    # Step 4: Attach to agent
    if create_agent:
        print("  [4/5] Creating new ORCHESTRATION agent...")
        prompt_id = find_orchestration_prompt(qconnect, assistant_id)
        tools = [mcp_tool] + get_return_to_control_tools()
        final_agent_id = create_agent_func(
            qconnect, assistant_id, instance_arn,
            agent_name, prompt_id, tools
        )
        result['agent_id'] = final_agent_id
        result['agent_created'] = True
        print(f"        Agent ID: {final_agent_id}")
    else:
        print(f"  [4/5] Adding tool to agent {agent_id}...")
        add_tool_to_agent(qconnect, assistant_id, agent_id, instance_arn, mcp_tool)
        result['agent_id'] = agent_id
        result['agent_created'] = False
        print("        Done")
    
    # Step 5: Add security permissions
    print("  [5/5] Adding security permissions...")
    profile_id = security_profile_id or find_admin_profile(connect, instance_id)
    add_security_permissions(connect, instance_id, profile_id, module_id)
    result['security_profile_id'] = profile_id
    print("        Done")
    
    print("\n" + "="*60)
    print("  ✓ MCP Tool created and attached successfully!")
    print("="*60)
    print(f"\nSummary:")
    print(f"  Tool Name:    {tool_name}")
    print(f"  Module ID:    {module_id}")
    print(f"  Version:      {version}")
    print(f"  toolId:       {mcp_tool['toolId']}")
    print(f"  Agent ID:     {result['agent_id']}")
    if result.get('agent_created'):
        print(f"  Agent Name:   {agent_name} (newly created)")
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Create and attach MCP tool to Connect AI Agent')
    parser.add_argument('--interactive', '-i', action='store_true', 
                        help='Run in interactive mode (guided setup)')
    parser.add_argument('--region', help='AWS region')
    parser.add_argument('--instance-id', help='Connect instance ID')
    parser.add_argument('--lambda-arn', help='Lambda function ARN')
    parser.add_argument('--tool-name', help='Tool name (e.g., CheckRefund)')
    parser.add_argument('--tool-description', help='Tool description for AI')
    parser.add_argument('--assistant-id', help='Q Connect Assistant ID')
    parser.add_argument('--agent-id', help='Existing agent ID to add tool to')
    parser.add_argument('--create-agent', action='store_true', help='Create new agent')
    parser.add_argument('--agent-name', default='MCP-Tool-Agent', help='Name for new agent')
    parser.add_argument('--security-profile-id', help='Security profile ID (defaults to Admin)')
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
            'security_profile_id': args.security_profile_id
        }
    
    # Confirm before proceeding
    print("\n--- Configuration ---")
    print(f"  Region:      {config['region']}")
    print(f"  Instance:    {config['instance_id']}")
    print(f"  Lambda:      {config['lambda_arn']}")
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

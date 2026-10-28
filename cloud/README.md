# Cloud deployment notes

Follow the [step-by-step deployment guide](../README.md#deploy-to-your-aws-account) from a fresh checkout. All helper scripts accept `--profile`, or use `AWS_PROFILE` and the standard AWS credential chain. There are no account IDs or credentials to edit in source code.

## Resources and authentication

Three independent Terraform roots manage the demo:

| Root | Resources |
| --- | --- |
| `alpha-vantage-mcp/infra` | MCP runtime and IAM role, ECR repository, Alpha Vantage secret metadata |
| `company-agent/infra` | Analyst runtime and IAM role, ECR repository, Bedrock application inference profile |
| `cloud/build` | Private encrypted S3 source bucket, ARM CodeBuild projects, build role, build logs |

AgentCore endpoints require AWS SigV4. The agent signs MCP requests using its runtime role. The MCP role reads only its own secret; the agent has no access to the Alpha Vantage key. The `PUBLIC` network setting provides outbound internet access, while IAM authenticates inbound invocations. See [AWS's MCP hosting guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html).

CodeBuild uploads include only the explicit source allowlists in `build_images.py`. They exclude local dotenv files, Terraform state, Git history and model downloads. S3 expires source archives after seven days; CodeBuild logs have seven-day retention. Builds run on demand.

## Configuration and state

The guide uses `eu-west-1`. Set `aws_region` consistently in both runtime configurations and `TF_VAR_aws_region` for all three Terraform roots if changing regions; choose an available model/inference profile for that region. Other region/model combinations have not been verified by this demo.

The build projects look up `company-agent-dev` and `alpha-vantage-mcp-dev`. If changing project/environment names, update `locals.projects` in `cloud/build/main.tf` too. For multiple demos in the same account, also give the build bucket, role, log group and projects distinct names. The optional GitHub OIDC and remote-backend definitions inherited from the blueprint are not enabled by this guide.

Persist `container_tag` and `mcp_runtime_arn` in the ignored `terraform.tfvars` files. Applying Terraform with stale values can revert a runtime version or its MCP connection. Preserve all three state files, even after cloning this Git repository elsewhere. Configure private remote state before sharing management of a deployment.

Provider lockfiles and Python lockfiles are committed. Local state, plans, tfvars, build records and test evidence are ignored. `cloud/builds.json` records the latest image tag, build IDs and source hashes locally.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Bedrock `AccessDeniedException` | Run the model check in step 2 with the provisioning profile. Confirm model availability, first-use requirements, Marketplace activation, IAM policies and organization restrictions. |
| ECR repository not found during build setup | Complete both bootstrap applies in step 3; keep ECR names consistent with `locals.projects`. |
| CodeBuild fails | Run `build_images.py status`; follow the returned log links. Do not deploy the tag until both builds succeed. |
| MCP cannot load its API key | Run `set_api_key.py` after the secret has been created, then start a new runtime session. Fixture mode does not read the secret value. |
| Alpha Vantage quota/access error | Inspect the partial snapshot's `errors`. Use a key with the required access and wait for your quota window before retrying. There is no automatic fixture fallback. |
| Signed client receives 403 | Check the selected AWS profile and permission to invoke the relevant runtime/endpoint. An unsigned request receiving 401/403 is expected. |
| Newly deployed runtime is not ready | Inspect its status in the AgentCore console and retry after it is ready; examine runtime logs if startup failed. |
| Secret name is unavailable after destroy | Secrets have a seven-day recovery window. Restore the scheduled-for-deletion secret and import it into Terraform, or wait before recreating that name. |

## Keys and verification

`set_api_key.py` prompts without echoing the key. For automation, it can instead read a private dotenv file containing `ALPHA_VANTAGE_API_KEY`:

```bash
uv run --project company-agent/agents --frozen python cloud/set_api_key.py \
  --env-file /absolute/path/to/private.env
```

The key is written directly to Secrets Manager, outside Terraform state. The runtime loads it at startup. New invocations through the supplied CLI use fresh session IDs.

`test_end_to_end.py --mode fixture` verifies known synthetic metrics and real model tool use. `--mode live` requires a complete live snapshot and asks the agent to analyze financial performance. It writes account-specific results to ignored `evidence/cloud/`. `--allow-partial` permits a partial live quote/overview demonstration; it does not prove complete statement access.

For cleanup, use the three destroy commands in the main README with the same AWS profile and state. The build bucket and development ECR repositories allow their contents to be deleted. Runtime-created log groups may remain after Terraform destroy.

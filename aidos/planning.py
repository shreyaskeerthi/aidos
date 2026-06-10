"""Runbook and execution plan generation for AIDOS."""

from __future__ import annotations

from typing import Any

import yaml

from aidos.schemas import CanonicalSoT, RunbookPlan, RunbookTask, ValidationReport


_INTENT_TO_PLAYBOOK = {
    "sync_netbox_intent": "claim_device_policy.yml",
    "configure_network": "network_connectivity_policy.yml",
    "provision_compute": "server_profile_template.yml",
    "post_deploy_health_check": "syslog_policy.yml",
}

_INTERSIGHT_PLAYBOOK_SEQUENCE = [
    "bios_policy.yml",
    "boot_order_policy.yml",
    "chassis_profile_template.yml",
    "claim_device_policy.yml",
    "domain_profile_template.yml",
    "eth_adapter_policy.yml",
    "eth_network_control_policy.yml",
    "eth_network_group_policy_storage.yml",
    "eth_network_group_policy.yml",
    "eth_qos_policy.yml",
    "firmware_policy.yml",
    "flow_control_policy.yml",
    "imc_access_policy.yml",
    "ip_pools.yml",
    "ipmi_policy.yml",
    "lan_connectivity.yml",
    "link_aggregation_policy.yml",
    "link_control_policy.yml",
    "local_user_policy.yml",
    "local_user.yml",
    "mac_pools.yml",
    "multicast_policy.yml",
    "network_connectivity_policy.yml",
    "ntp_policy.yml",
    "port_policy.yml",
    "power_policy.yml",
    "sever_profile_template.yml",
    "snmp_policy.yml",
    "storage_policy.yml",
    "switch_control_policy.yml",
    "syslog_policy.yml",
    "system_qos_policy.yml",
    "thermal_policy.yml",
    "updated_vlan_policy.yml",
    "uuid_pool.yml",
    "vkvm_policy.yml",
    "vlan_policy.yml",
    "vmedia_policy.yml",
    "vnic_templates.yml",
]

_ARCHITECTURE_PLAYBOOKS = {
    "intersight": "arch_intersight.yml",
    "netbox": "arch_netbox.yml",
    "kubernetes": "arch_kubernetes.yml",
    "storage": "arch_storage.yml",
    "observability": "arch_observability.yml",
    "security": "arch_security.yml",
    "gitops": "arch_gitops.yml",
    "cicd": "arch_cicd.yml",
    "disaster_recovery": "arch_disaster_recovery.yml",
}


def build_runbook_plan(
    sot: CanonicalSoT,
    report: ValidationReport,
    *,
    pyats_testbed_path: str | None = None,
) -> RunbookPlan:
    """Generate normalized runbook tasks from SoT + validation findings."""
    deployment = sot.intent.deployment_name
    post_check_executor = "pyats" if pyats_testbed_path else "cli"
    post_check_fallbacks = ["cli", "api", "ansible", "mcp", "playwright"]

    tasks = [
        RunbookTask(
            id="task-001",
            intent="sync_netbox_intent",
            target=deployment,
            preferred_executor="api",
            fallback_executors=["cli", "ansible", "mcp", "playwright"],
            preconditions=["sot_built"],
            approval_required=False,
        ),
        RunbookTask(
            id="task-002",
            intent="configure_network",
            target="switch-stack-a",
            preferred_executor="ansible",
            fallback_executors=["api", "cli", "mcp", "playwright"],
            preconditions=["netbox_synced", "validation_passed"],
            approval_required=True,
        ),
        RunbookTask(
            id="task-003",
            intent="provision_compute",
            target=deployment,
            preferred_executor="api",
            fallback_executors=["ansible", "cli", "mcp", "playwright"],
            preconditions=["netbox_synced", "validation_passed"],
            approval_required=True,
        ),
        RunbookTask(
            id="task-004",
            intent="post_deploy_health_check",
            target=deployment,
            preferred_executor=post_check_executor,
            fallback_executors=post_check_fallbacks,
            preconditions=["execution_complete"],
            approval_required=False,
        ),
    ]

    notes = [
        "Executor priority order: api > cli > ansible > mcp > playwright; post-check optionally promotes pyATS when configured.",
        f"Validation readiness at planning time: {report.readiness}",
    ]
    if pyats_testbed_path:
        notes.append(f"pyATS health-check enabled using testbed: {pyats_testbed_path}")
    else:
        notes.append("pyATS health-check not configured; post-deploy verification falls back to CLI.")
    if report.critical:
        notes.append("Critical findings exist: execution should remain approval-gated.")

    return RunbookPlan(deployment=deployment, tasks=tasks, notes=notes)


def build_ansible_playbook(plan: RunbookPlan) -> str:
    """Generate site.yml style master playbook importing child playbooks."""
    imports = []
    for task in plan.tasks:
        playbook_name = _INTENT_TO_PLAYBOOK.get(task.intent, f"{task.id}_{task.intent}.yml")
        imports.append({"import_playbook": f"playbooks/{playbook_name}"})
    return yaml.safe_dump(imports, sort_keys=False)


def build_ansible_bundle(
    plan: RunbookPlan,
    *,
    architecture: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Generate intersight-style ansible bundle files for operator usability."""
    files: dict[str, str] = {}
    architecture = architecture or {}

    project = architecture.get("project", {}) if isinstance(architecture.get("project"), dict) else {}
    intent = architecture.get("intent", {}) if isinstance(architecture.get("intent"), dict) else {}
    expected = architecture.get("expected", {}) if isinstance(architecture.get("expected"), dict) else {}
    netbox = architecture.get("netbox_payload", {}) if isinstance(architecture.get("netbox_payload"), dict) else {}

    project_name = str(project.get("project_name") or plan.deployment)
    customer_name = str(project.get("customer_name") or "unknown-customer")
    site_name = str(project.get("site_name") or project_name)
    region = str(project.get("region") or "unknown-region")
    node_count = int(intent.get("node_count") or 0)
    gpu_model = str(intent.get("gpu_model") or "unknown-gpu")
    required_vlans = intent.get("required_vlans") if isinstance(intent.get("required_vlans"), list) else []

    netbox_counts = {
        "sites": len(netbox.get("sites", [])) if isinstance(netbox.get("sites"), list) else 0,
        "racks": len(netbox.get("racks", [])) if isinstance(netbox.get("racks"), list) else 0,
        "devices": len(netbox.get("devices", [])) if isinstance(netbox.get("devices"), list) else 0,
        "vlans": len(netbox.get("vlans", [])) if isinstance(netbox.get("vlans"), list) else 0,
        "prefixes": len(netbox.get("prefixes", [])) if isinstance(netbox.get("prefixes"), list) else 0,
    }

    architecture_packs: dict[str, Any] = {
        "intersight": {
            "platform": str(intent.get("target_platform") or "Cisco AI Pod"),
            "deployment": plan.deployment,
            "policy_count": len(_INTERSIGHT_PLAYBOOK_SEQUENCE),
            "profile_model": f"Generic GPU Node {gpu_model}",
        },
        "netbox": {
            "objects": netbox_counts,
            "intent_sync": "enabled",
            "source_of_truth": "aidos canonical_sot + netbox_payload",
        },
        "kubernetes": {
            "cluster_name": f"{project_name}-k8s",
            "distribution": "upstream-kubernetes",
            "control_plane_topology": "3-node highly-available",
            "worker_gpu_nodes": node_count,
            "cni": "cilium",
            "ingress": "nginx",
            "runtime": "containerd",
        },
        "storage": {
            "backends": ["ceph-rbd", "nfs"],
            "storage_classes": ["fast-gpu", "bulk-archive"],
            "snapshot_policy": "hourly-24h-daily-30d",
        },
        "observability": {
            "metrics": "prometheus",
            "dashboards": "grafana",
            "logs": "loki",
            "traces": "tempo",
            "alerting": "alertmanager",
        },
        "security": {
            "identity": "oidc + mfa",
            "secrets": "vault",
            "network_policy": "zero-trust east-west",
            "image_security": "signed-images + vuln-scan",
            "audit_retention_days": 365,
        },
        "gitops": {
            "controller": "argocd",
            "branch_strategy": "main + protected",
            "promotion_flow": "dev->staging->prod",
        },
        "cicd": {
            "pipeline": "github-actions",
            "stages": ["lint", "test", "security", "deploy"],
            "artifact_store": "oci-registry",
        },
        "disaster_recovery": {
            "strategy": "warm-standby",
            "rpo_minutes": 15,
            "rto_minutes": 60,
            "backup_targets": ["object-storage", "offsite-snapshot"],
        },
    }

    # Allow caller-supplied project metadata to augment architecture packs.
    for key in ["security_requirements", "operations", "network_architecture", "compute_architecture"]:
        if key in project:
            architecture_packs["intersight"][key] = project[key]

    files["README.md"] = "\n".join(
        [
            "# AIDOS Generated Ansible Bundle",
            "",
            "This bundle mirrors policy-oriented Intersight-style structure for deployment readiness.",
            "",
            "## Quick Start",
            "",
            "1. Populate group_vars/all.yml from group_vars/all.yml.template",
            "2. Update inventory/hosts.yml as needed",
            "3. Run: ansible-playbook -i inventory/hosts.yml -e @group_vars/all.yml playbooks/site.yml",
            "4. Full-stack run: ansible-playbook -i inventory/hosts.yml -e @group_vars/all.yml playbooks/site_full_stack.yml",
            "",
            "## Architecture Snapshot",
            f"- Customer: {customer_name}",
            f"- Project: {project_name}",
            f"- Site: {site_name}",
            f"- Region: {region}",
            f"- GPU Model: {gpu_model}",
            f"- Node Count: {node_count}",
            f"- Required VLANs: {', '.join(str(v) for v in required_vlans) if required_vlans else 'none'}",
            f"- Estimated Power (kW): {expected.get('estimated_power_kw', 'n/a')}",
            f"- Estimated Cooling (kW): {expected.get('estimated_cooling_kw', 'n/a')}",
            "",
            "## NetBox Intent Payload",
            f"- Sites: {netbox_counts['sites']}",
            f"- Racks: {netbox_counts['racks']}",
            f"- Devices: {netbox_counts['devices']}",
            f"- VLANs: {netbox_counts['vlans']}",
            f"- Prefixes: {netbox_counts['prefixes']}",
            "",
            "## Generated from runbook",
            f"- Deployment: {plan.deployment}",
            f"- Tasks: {len(plan.tasks)}",
            "",
            "## Architecture Packs Included",
            "- intersight",
            "- netbox",
            "- kubernetes",
            "- storage",
            "- observability",
            "- security",
            "- gitops",
            "- cicd",
            "- disaster_recovery",
            "",
        ]
    )

    files["group_vars/all.yml.template"] = yaml.safe_dump(
        {
            "deployment_name": plan.deployment,
            "customer_name": customer_name,
            "project_name": project_name,
            "site_name": site_name,
            "region": region,
            "gpu_model": gpu_model,
            "node_count": node_count,
            "required_vlans": required_vlans,
            "api_key_id": "SET_ME",
            "api_private_key": "SET_ME",
            "org_name": "SET_ME",
            "prefix": plan.deployment.upper().replace("-", "_"),
            "netbox": {
                "site_count": netbox_counts["sites"],
                "rack_count": netbox_counts["racks"],
                "device_count": netbox_counts["devices"],
                "vlan_count": netbox_counts["vlans"],
                "prefix_count": netbox_counts["prefixes"],
            },
            "notes": "Generated by AIDOS planning module",
        },
        sort_keys=False,
    )
    files["group_vars/all.yml.example"] = files["group_vars/all.yml.template"]
    files["group_vars/architecture.yml"] = yaml.safe_dump(architecture, sort_keys=False)

    files["inventory/hosts.yml"] = yaml.safe_dump(
        {
            "all": {
                "hosts": {
                    "localhost": {
                        "ansible_connection": "local",
                    }
                }
            }
        },
        sort_keys=False,
    )

    task_by_playbook = {
        _INTENT_TO_PLAYBOOK.get(task.intent, f"{task.id}_{task.intent}.yml"): task
        for task in plan.tasks
    }

    site_imports = []
    for playbook_name in _INTERSIGHT_PLAYBOOK_SEQUENCE:
        site_imports.append({"import_playbook": playbook_name})
        task = task_by_playbook.get(playbook_name)
        task_info = {
            "task_id": task.id,
            "intent": task.intent,
            "target": task.target,
            "preferred_executor": task.preferred_executor,
            "approval_required": task.approval_required,
        } if task else {
            "task_id": "n/a",
            "intent": playbook_name.replace(".yml", ""),
            "target": plan.deployment,
            "preferred_executor": "ansible",
            "approval_required": False,
        }

        files[f"playbooks/{playbook_name}"] = yaml.safe_dump(
            [
                {
                    "name": f"AIDOS policy orchestration - {playbook_name}",
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {
                        "aidos_task": task_info,
                        "aidos_architecture": {
                            "project": project_name,
                            "site": site_name,
                            "region": region,
                            "gpu_model": gpu_model,
                            "node_count": node_count,
                            "required_vlans": required_vlans,
                        },
                    },
                    "tasks": [
                        {
                            "name": "Validate deployment context",
                            "assert": {
                                "that": [
                                    "aidos_architecture.project | length > 0",
                                    "aidos_architecture.site | length > 0",
                                ],
                                "quiet": True,
                            },
                        },
                        {
                            "name": "Prepare policy payload",
                            "set_fact": {
                                "policy_payload": {
                                    "deployment": "{{ deployment_name }}",
                                    "policy": playbook_name.replace(".yml", ""),
                                    "task": "{{ aidos_task }}",
                                }
                            },
                        },
                        {
                            "name": "Apply policy (placeholder)",
                            "debug": {
                                "msg": (
                                    "task={{ aidos_task.task_id }} intent={{ aidos_task.intent }} "
                                    "target={{ aidos_task.target }} executor={{ aidos_task.preferred_executor }} "
                                    "project={{ aidos_architecture.project }} site={{ aidos_architecture.site }}"
                                )
                            },
                        }
                    ],
                }
            ],
            sort_keys=False,
        )

    files["playbooks/site.yml"] = yaml.safe_dump(site_imports, sort_keys=False)

    # Emit architecture pack data and dedicated orchestration playbooks.
    for domain, payload in architecture_packs.items():
        files[f"architectures/{domain}.yml"] = yaml.safe_dump(payload, sort_keys=False)

    full_stack_imports = [{"import_playbook": "site.yml"}]
    for domain, playbook in _ARCHITECTURE_PLAYBOOKS.items():
        full_stack_imports.append({"import_playbook": playbook})
        files[f"playbooks/{playbook}"] = yaml.safe_dump(
            [
                {
                    "name": f"AIDOS architecture domain - {domain}",
                    "hosts": "localhost",
                    "gather_facts": False,
                    "tasks": [
                        {
                            "name": "Load architecture pack",
                            "include_vars": f"../architectures/{domain}.yml",
                            "register": "arch_pack",
                        },
                        {
                            "name": "Apply architecture domain (placeholder)",
                            "debug": {
                                "msg": (
                                    f"domain={domain} deployment={{ deployment_name }} "
                                    "payload={{ arch_pack.ansible_facts }}"
                                )
                            },
                        },
                    ],
                }
            ],
            sort_keys=False,
        )

    files["playbooks/site_full_stack.yml"] = yaml.safe_dump(full_stack_imports, sort_keys=False)

    files["docs/deployment_readiness_checklist.md"] = "\n".join(
        [
            "# Deployment Readiness Checklist",
            "",
            "## Core",
            "- [ ] Canonical SoT reviewed",
            "- [ ] NetBox reconciliation has no errors",
            "- [ ] Runbook approvals captured",
            "",
            "## Intersight",
            "- [ ] API credentials configured",
            "- [ ] All policy playbooks reviewed",
            "- [ ] site.yml dry run successful",
            "",
            "## Full Stack",
            "- [ ] Kubernetes architecture pack validated",
            "- [ ] Storage architecture pack validated",
            "- [ ] Observability architecture pack validated",
            "- [ ] Security controls validated",
            "- [ ] GitOps and CI/CD workflows validated",
            "- [ ] Disaster recovery objectives approved",
            "",
            "## Production Gate",
            "- [ ] Execute playbooks/site_full_stack.yml in change window",
            "- [ ] Post-deploy health check passed",
        ]
    )

    return files


def build_agentic_task_graph(plan: RunbookPlan) -> dict[str, Any]:
    """Generate agentic task graph JSON for NemoClaw/Nemosys style runtime."""
    nodes = [
        {
            "id": task.id,
            "intent": task.intent,
            "target": task.target,
            "preferred_executor": task.preferred_executor,
            "fallback_executors": task.fallback_executors,
            "preconditions": task.preconditions,
            "approval_required": task.approval_required,
            "evidence_required": task.evidence_required,
        }
        for task in plan.tasks
    ]

    edges = []
    for idx in range(len(plan.tasks) - 1):
        edges.append({"from": plan.tasks[idx].id, "to": plan.tasks[idx + 1].id})

    return {
        "deployment": plan.deployment,
        "nodes": nodes,
        "edges": edges,
        "notes": plan.notes,
    }

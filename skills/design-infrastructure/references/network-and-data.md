# Network, compute and databases: private by default (AWS and GCP)

Reuse the project's existing modules (or the official `terraform-aws-modules/vpc`, `terraform-google-modules/network` if the project already uses them). The shapes below are what to check for, not a new architecture to impose.

## Network layout

| Tier | AWS | GCP | Reachable from |
| --- | --- | --- | --- |
| Public | public subnets: ALB/NLB, NAT gateways only | external HTTPS load balancer (global), Cloud NAT on the router | internet (80/443 only) |
| Private app | private subnets per AZ: EC2/ECS/EKS/Lambda in VPC | subnet per region, VMs/GKE without external IPs | the load balancer's security group / health-check ranges |
| Data | isolated subnets (no NAT route) in a DB subnet group | Cloud SQL private IP via Private Service Access | app tier only |

- At least two AZs (AWS) for anything shared; one NAT per AZ for production, one shared NAT is acceptable for dev.
- Reach AWS/GCP services privately: S3/DynamoDB **gateway endpoints** (free), interface endpoints for ECR, Secrets Manager, SSM, STS, CloudWatch Logs when the subnets have no NAT; GCP **Private Google Access** on subnets.
- Security groups: rules reference other security groups (`source_security_group_id` / `referenced_security_group_id`), not CIDR ranges; egress narrowed where the workload allows. NACLs only as a coarse extra layer.
- GCP firewall rules target **service accounts** (`target_service_accounts`) rather than network tags; deny-by-default stays; restrict SSH to the IAP range `35.235.240.0/20`.
- Admin access: AWS SSM Session Manager (instance role with `AmazonSSMManagedInstanceCore`, VPC endpoints for ssm/ssmmessages/ec2messages) or GCP IAP TCP forwarding. No bastion with public SSH, no key pairs to share.
- Org guardrails when the project manages them: AWS SCPs, GCP org policies (`compute.vmExternalIpAccess`, `iam.disableServiceAccountKeyCreation`, `sql.restrictPublicIp`, `storage.publicAccessPrevention`).

```hcl
# App security group accepts traffic only from the load balancer's security group.
resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}
```

## Compute

AWS EC2 / launch template:

```hcl
resource "aws_launch_template" "app" {
  image_id               = data.aws_ami.al2023.id
  instance_type          = "t3.small"
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile { name = aws_iam_instance_profile.app.name } # role with only what the app calls
  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1          # 2 only when containers on the host need the role
  }
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      encrypted   = true
      volume_type = "gp3"
    }
  }
  # no associate_public_ip_address; subnets are private
}
```

GCP GCE: no `access_config` in `network_interface`; a dedicated service account (`service_account` block with `email = google_service_account.app.email` and the `cloud-platform` scope) whose IAM roles carry the limits; Shielded VM on; OS Login instead of SSH keys in metadata.

Containers: ECS task role (app permissions) separate from the task execution role (pull image, read its secrets); EKS IRSA or Pod Identity per service account; GKE Workload Identity per Kubernetes service account.

## Databases

AWS RDS / Aurora:

```hcl
resource "aws_db_instance" "main" {
  engine                      = "postgres"
  instance_class              = "db.t4g.medium"
  db_subnet_group_name        = aws_db_subnet_group.data.name # isolated subnets
  vpc_security_group_ids      = [aws_security_group.db.id]    # ingress only from the app SG
  publicly_accessible         = false
  storage_encrypted           = true
  kms_key_id                  = aws_kms_key.data.arn
  manage_master_user_password = true # Secrets Manager, rotated; no password in code or state outputs
  iam_database_authentication_enabled = true
  backup_retention_period     = 7
  deletion_protection         = true
  multi_az                    = var.environment == "production"
  parameter_group_name        = aws_db_parameter_group.pg.name # rds.force_ssl = 1
  auto_minor_version_upgrade  = true
}
```

Connection pooling: size pools with `DS pool-budget` (change-database); RDS Proxy when many short-lived clients (Lambda) connect.

GCP Cloud SQL:

```hcl
resource "google_sql_database_instance" "main" {
  database_version    = "POSTGRES_16"
  deletion_protection = true
  settings {
    tier              = "db-custom-2-7680"
    availability_type = var.environment == "production" ? "REGIONAL" : "ZONAL"
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }
  }
}
```

Apps connect through the Cloud SQL Auth Proxy or language connectors with IAM database authentication.

Buckets: AWS S3 Block Public Access on (all four flags), `aws_s3_bucket_ownership_controls` = BucketOwnerEnforced, default encryption, TLS-only bucket policy (`aws:SecureTransport`); GCP `uniform_bucket_level_access = true`, `public_access_prevention = "enforced"`. Public content through CloudFront with Origin Access Control or Cloud CDN, never a public bucket.

## Review checklist for a plan

- Every `-/+ replace` and `destroy`: is data lost (DB, volume, bucket)? Is there a snapshot/backup first?
- Every IAM change: which principal gains which actions on which resources, and why.
- Every network change: what becomes reachable from where; anything new on 0.0.0.0/0.
- Cost: NAT gateways, interface endpoints, multi-AZ, instance sizes.
- Rollback: the previous module version and whether rolling back is itself destructive.

# Least-privilege IAM (AWS and GCP)

Each workload gets its own identity with only the actions it performs, on only its resources, under conditions that narrow where and how. Humans use SSO with short sessions; machines never use long-lived keys.

## 1. Derive the permissions from the code

1. List the SDK calls the workload makes (search the code: `boto3.client("s3")…put_object`, `S3Client.send(new PutObjectCommand…)`, `Storage::disk('s3')->put`, `storage.Client().bucket(...).blob(...).upload_from_string`).
2. Map each call to its action (`put_object` → `s3:PutObject`; KMS-encrypted bucket → also `kms:GenerateDataKey`/`kms:Decrypt` on that key) and to the resource it touches (bucket + prefix, table, queue, secret, key).
3. Write one statement per resource group; reads and writes separate when different workloads need them.
4. Confirm with the project's tools when available (the user runs them; they read the account): IAM Access Analyzer policy validation and policy generation from CloudTrail in a non-production account, `aws iam simulate-principal-policy`; GCP IAM Recommender and Policy Troubleshooter.

## 2. AWS shapes

```hcl
# App role: read/write its own tenant uploads prefix, read one secret, use one KMS key only through S3/Secrets Manager.
data "aws_iam_policy_document" "app" {
  statement {
    sid       = "UploadsObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/tenants/*"]
  }
  statement {
    sid       = "UploadsList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.uploads.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["tenants/*"]
    }
  }
  statement {
    sid       = "AppSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
  statement {
    sid       = "DataKeyViaServices"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.region}.amazonaws.com", "secretsmanager.${var.region}.amazonaws.com"]
    }
  }
}
```

Trust policies decide *who* can assume the role:

```hcl
# GitHub Actions deploy role: only this repo's main branch (or a protected environment) can assume it.
data "aws_iam_policy_document" "ci_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:acme/shop:ref:refs/heads/main"]
    }
  }
}
```

- Useful conditions: `aws:SourceVpce` / `aws:SourceVpc` (only from your network), `aws:PrincipalTag` / `aws:ResourceTag` (attribute-based access per tenant/team), `aws:RequestedRegion`, `kms:ViaService`, `aws:SecureTransport`, `s3:prefix`.
- `iam:PassRole` only for the role ARNs the service really passes, with `iam:PassedToService`.
- Permission boundaries on roles that developers or CI may create; SCPs for account-wide denies (regions, disabling CloudTrail, leaving the organization).
- Resource policies (bucket, KMS key, SQS, Lambda permission) name principals and use `aws:SourceArn` / `aws:SourceAccount` for service principals (confused-deputy protection).
- AWS managed policies like `AmazonS3FullAccess`, `PowerUserAccess`, `AdministratorAccess` are never attached to workloads.

## 3. GCP shapes

```hcl
resource "google_service_account" "app" {
  account_id   = "orders-api"
  display_name = "orders API (Cloud Run)"
}

# Grant on the bucket, not the project.
resource "google_storage_bucket_iam_member" "app_uploads" {
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "app_secret" {
  secret_id = google_secret_manager_secret.app.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

# CI deploys through Workload Identity Federation, restricted to one repository.
resource "google_service_account_iam_member" "ci_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/acme/shop"
}
```

- Prefer resource-level bindings (bucket, secret, topic, dataset) over project-level ones; predefined narrow roles over primitive `roles/owner`/`roles/editor`/`roles/viewer`; custom roles when no predefined role is narrow enough.
- IAM Conditions for time-bound or resource-name-bound grants (`resource.name.startsWith(...)`).
- `roles/iam.serviceAccountUser` / `serviceAccountTokenCreator` granted on one service account, never project-wide.
- No service account keys (`iam.disableServiceAccountKeyCreation`); Workload Identity on GKE, attached service accounts on Cloud Run/GCE, WIF for CI.
- Never bind `allUsers` / `allAuthenticatedUsers` except a reviewed public asset bucket behind a CDN.

## 4. Humans

- AWS IAM Identity Center (SSO) permission sets / GCP groups; MFA; short sessions; no IAM users with access keys.
- Separate read-only and admin permission sets; production write access is time-bound and audited; break-glass account sealed and alerted.

## 5. Red flags → fix

| Seen in the diff | Fix |
| --- | --- |
| `"Action": "*"` or `AdministratorAccess` on a workload | Enumerate the calls (section 1) |
| `"Resource": "*"` with write actions | ARNs of the resources the code touches |
| `NotAction` in an Allow | Explicit Allow list |
| `iam:PassRole` on `*` | Specific role ARNs + `iam:PassedToService` |
| `Principal: "*"` without conditions | Named accounts/roles, or `aws:SourceVpce` / `aws:PrincipalOrgID` |
| OIDC trust without `sub` | Pin repository and branch/environment |
| `aws_iam_access_key`, SA key resource | Roles / federation |
| `roles/editor` on a service account | Narrow roles on specific resources |

`DS check-infra` flags these in Terraform, CloudFormation and policy JSON; checkov/trivy (via `native-checks`) add hundreds more.

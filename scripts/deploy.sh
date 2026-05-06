#!/usr/bin/env bash
# End-to-end deploy: EKS cluster → Helm releases → K8s Jobs
# Usage: bash scripts/deploy.sh
# Requires: terraform, aws CLI, kubectl, helm, docker
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$REPO_ROOT/terraform"
K8S_DIR="$REPO_ROOT/k8s"
NAMESPACE="day20"

# ── 1. Terraform apply ────────────────────────────────────────────────────────
echo "==> [1/8] Terraform apply"
cd "$TF_DIR"
terraform init -input=false
terraform apply -auto-approve -input=false

CLUSTER_NAME=$(terraform output -raw cluster_name)
AWS_REGION=$(terraform output -json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('aws_region',{}).get('value','us-east-1'))" 2>/dev/null || echo "us-east-1")
ECR_URL=$(terraform output -raw ecr_pipeline_url)
RDS_ENDPOINT=$(terraform output -raw rds_endpoint)
cd "$REPO_ROOT"

# ── 2. kubeconfig ─────────────────────────────────────────────────────────────
echo "==> [2/8] Updating kubeconfig"
aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"
kubectl get nodes

# ── 3. Namespace + HF Secret ─────────────────────────────────────────────────
echo "==> [3/8] Namespace + secrets"
kubectl apply -f "$K8S_DIR/namespace.yaml"

# HF_TOKEN must be set in environment before running this script
if [[ -z "${HF_TOKEN:-}" ]]; then
  echo "ERROR: Set HF_TOKEN env var before running deploy.sh"
  exit 1
fi
kubectl create secret generic hf-secret \
  --from-literal=token="$HF_TOKEN" \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

# ── 4. Helm: Milvus ───────────────────────────────────────────────────────────
echo "==> [4/8] Helm install Milvus"
helm repo add milvus https://zilliztech.github.io/milvus-helm 2>/dev/null || true
helm repo update milvus
helm upgrade --install milvus milvus/milvus \
  --namespace "$NAMESPACE" \
  --values "$K8S_DIR/helm/milvus-values.yaml" \
  --wait --timeout 10m

# ── 5. Helm: Redis ────────────────────────────────────────────────────────────
echo "==> [5/8] Helm install Redis"
helm repo add bitnami https://charts.bitnami.com/bitnami 2>/dev/null || true
helm repo update bitnami
helm upgrade --install redis bitnami/redis \
  --namespace "$NAMESPACE" \
  --values "$K8S_DIR/helm/redis-values.yaml" \
  --wait --timeout 5m

# ── 6. Helm: SGLang ───────────────────────────────────────────────────────────
echo "==> [6/8] Helm install SGLang"
helm upgrade --install sglang "$K8S_DIR/helm/sglang" \
  --namespace "$NAMESPACE" \
  --wait --timeout 15m  # model download takes time on first start

# ── 7. Docker build + push to ECR ────────────────────────────────────────────
echo "==> [7/8] Build and push Docker images to ECR"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_URL"

# pipeline image
docker build -t "${ECR_URL}:latest" \
  -f "$K8S_DIR/pipeline-job/Dockerfile" \
  --build-context day19="../TranThuongTruongSon_Day19_Track2" \
  "$REPO_ROOT"
docker push "${ECR_URL}:latest"

# setup-milvus image
docker build -t "${ECR_URL}:setup" \
  -f "$K8S_DIR/setup-milvus-job/Dockerfile" \
  "$REPO_ROOT"
docker push "${ECR_URL}:setup"

# Patch image URLs into job manifests
sed -i "s|<ECR_URL>|${ECR_URL}|g" "$K8S_DIR/pipeline-job/job.yaml"
sed -i "s|<ECR_URL>|${ECR_URL}|g" "$K8S_DIR/setup-milvus-job/job.yaml"

# ── 8. Run Jobs ───────────────────────────────────────────────────────────────
echo "==> [8/8] Run setup-milvus Job then pipeline Job"

kubectl apply -f "$K8S_DIR/pipeline-job/configmap.yaml"

kubectl delete job setup-milvus-job -n "$NAMESPACE" --ignore-not-found
kubectl apply -f "$K8S_DIR/setup-milvus-job/job.yaml"
echo "  Waiting for setup-milvus-job to complete..."
kubectl wait --for=condition=complete job/setup-milvus-job -n "$NAMESPACE" --timeout=600s
kubectl logs -n "$NAMESPACE" job/setup-milvus-job

kubectl delete job pipeline-job -n "$NAMESPACE" --ignore-not-found
kubectl apply -f "$K8S_DIR/pipeline-job/job.yaml"
echo "  Waiting for pipeline-job to complete..."
kubectl wait --for=condition=complete job/pipeline-job -n "$NAMESPACE" --timeout=300s
echo ""
echo "==> pipeline-job logs:"
kubectl logs -n "$NAMESPACE" job/pipeline-job

echo ""
echo "==> Deploy complete!"
echo "    kubectl get pods -n $NAMESPACE"
echo "    kubectl logs -n $NAMESPACE job/pipeline-job"

#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${REPO_ROOT}/.venv/bin/python"
if [ ! -x "${PYTHON}" ]; then
  PYTHON="python"
fi

run_generate_proto() {
  local service_path="$1"
  local service_name=$(basename "$service_path")
  local package_name="${service_name//-/_}"
  local proto_dir="${service_path}/proto"
  local src_dir="${service_path}/src"

  "${PYTHON}" \
    -m grpc_tools.protoc \
    -I "${proto_dir}" \
    --python_out="${src_dir}/${package_name}/proto" \
    --grpc_python_out="${src_dir}/${package_name}/proto" \
    --pyi_out="${src_dir}/${package_name}/proto" \
    "${proto_dir}"/*.proto

  # Normalize generated files to LF line endings (grpc_tools.protoc may emit CRLF)
  find "${src_dir}/${package_name}/proto" -name "*.py" -o -name "*.pyi" | xargs sed -i 's/\r//'
}

run_generate_proto "services/stream-api"
run_generate_proto "services/rest-api"
echo "Proto regeneration complete."

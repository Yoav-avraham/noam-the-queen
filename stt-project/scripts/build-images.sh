#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build-images.sh
# Iterates over every service under services/, builds each image, and exports
# it to ./archive/<service>.tar.
# Generic file (repo root):
#   Dockerfile.deps  — installs Python dependencies; receives SERVICE_NAME arg
#
# Each service owns its Dockerfile.  Standard Python services (those with a
# pyproject.toml whose Dockerfile inherits from a *-deps image) get their
# deps layer built first from the generic Dockerfile.deps.
# Non-standard services (e.g. the inference placeholder) are built directly.
#
# Usage:  ./build-images.sh [service-name ...]
#   With no arguments, all services are processed.
#   With arguments, only the named services are processed.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICES_DIR="$REPO_ROOT/services"
OUTPUT_DIR="$REPO_ROOT/archive"
GENERIC_DOCKERFILE_DEPS="$REPO_ROOT/Dockerfile.deps"


mkdir -p "$OUTPUT_DIR"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Convert a service directory name to a Python module name (dashes → underscores)
module_name() { echo "${1//-/_}"; }


# Return 0 if the service uses the standard generic Python build pipeline:
#   - Has a pyproject.toml (it's a Python package), AND
#   - Either has no Dockerfile of its own, or its Dockerfile's FROM references
#     a *-deps image (meaning it was generated from the standard template).
is_standard_python_service() {
    local service_dir="$1"
    [[ -f "$service_dir/pyproject.toml" ]] || return 1
    local dockerfile="$service_dir/Dockerfile"
    if [[ -f "$dockerfile" ]]; then
        grep -qE '^FROM\s+\S+-deps' "$dockerfile" || return 1
    fi
    return 0
    
}

# ---------------------------------------------------------------------------
# Per-service build logic
# ---------------------------------------------------------------------------

build_service() {
    local service_name="$1"
    local service_dir="$SERVICES_DIR/$service_name"

    echo ""
    echo "==> $service_name"

    if [[ ! -f "$service_dir/Dockerfile" ]]; then
        echo "  [skip] No Dockerfile found."
        return
    fi

    local image_tag
    if is_standard_python_service "$service_dir"; then
        # Build deps layer first (layer-cached separately for faster rebuilds)
        local deps_tag="${service_name}-deps"
        echo "  Building ${deps_tag} ...!"
        if [[ ${service_name} == "inference-adapter" ]]; then
            docker build \
                --file "$GENERIC_DOCKERFILE_DEPS" \
                --build-arg SERVICE_NAME="$service_name" \
                --build-arg VERSION="3.12" \
                --tag "${deps_tag}" \
                "$REPO_ROOT"
        else
            docker build \
                --file "$GENERIC_DOCKERFILE_DEPS" \
                --build-arg SERVICE_NAME="$service_name" \
                --tag "${deps_tag}" \
                "$REPO_ROOT"
        fi

        # # Build the final service image on top of the deps layer
        # image_tag="${service_name}"
        # echo "  Building ${image_tag} ...?"
        # docker build \
        #     --file "$service_dir/Dockerfile" \
        #     --tag "${image_tag}" \
        #     "$REPO_ROOT"
    else
        # Non-standard service: build directly from its own Dockerfile
        image_tag="${service_name}"
        echo "  Building ${image_tag} ..."
        docker build \
            --file "$service_dir/Dockerfile" \
            --tag "${image_tag}" \
            "$REPO_ROOT"
    fi

    # Only save the final service image to archive (deps stay local only)
    # local output_file="$OUTPUT_DIR/${service_name}.tar"
    # echo "  Saving → $output_file"
    # docker save "${image_tag}" -o "$output_file"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SKIP_SERVICES=(inference)

if [[ $# -gt 0 ]]; then
    # Build only the services passed as arguments
    for svc in "$@"; do
        build_service "$svc"
    done
else
    # Build every subdirectory under services/
    for service_dir in "$SERVICES_DIR"/*/; do
        svc="$(basename "$service_dir")"
        if [[ " ${SKIP_SERVICES[*]} "  == *" $svc "* ]]; then
            echo ""
            echo "==> $svc [skip] (in SKIP_SERVICES list)"

        else
            build_service "$svc"
        fi
    done
fi

echo ""
echo "Done. Images saved to $OUTPUT_DIR/"

# usage examples:
# Build all services
# ./build-images.sh

#  Build specific services only
# ./build-images.sh stream-api synchronizer



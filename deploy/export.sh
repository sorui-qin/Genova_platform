#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "Usage: bash export.sh OUTPUT_DIRECTORY VERSION [IMAGE_REPOSITORY]" >&2
    exit 2
fi
output=$1
export PLATFORM_VERSION=$2 IMAGE_REPOSITORY=${3:-genova}
[[ $PLATFORM_VERSION =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$ && $IMAGE_REPOSITORY =~ ^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$ ]] || {
    echo 'Invalid version or image repository' >&2
    exit 2
}
[[ ! -e $output ]] || { echo "Output already exists: $output" >&2; exit 1; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# 仅解析镜像名称；不读取或导出源实例的密钥。
export POSTGRES_PASSWORD=export-placeholder REDIS_PASSWORD=export-placeholder JWT_SECRET=export-placeholder
image_list=$(docker compose --env-file "$root/.env.example" -f "$root/compose.yml" config --images | sort -u)
[[ -n $image_list ]] || { echo 'No images found' >&2; exit 1; }
mapfile -t images <<< "$image_list"
docker image inspect "${images[@]}" --format '{{.Id}}' >/dev/null

mkdir -p -- "$(dirname -- "$output")"
staging=$(mktemp -d "${output}.tmp.XXXXXX")
trap 'rm -rf -- "$staging"' EXIT
cp "$root/compose.yml" "$root/README.md" "$root/README.en.md" "$root/DELETE.md" "$root/EPSO.md" "$root/SURFGEN_COMPATIBILITY.md" "$root/../README.zh-CN.md" "$staging/"
{
    printf 'IMAGE_REPOSITORY=%s\nPLATFORM_VERSION=%s\n' "$IMAGE_REPOSITORY" "$PLATFORM_VERSION"
    tail -n +3 "$root/.env.example"
} > "$staging/.env.example"
printf '%s\n' "${images[@]}" > "$staging/images.txt"
for image in "${images[@]}"; do
    printf '%s ' "$image"
    docker image inspect "$image" --format '{{.Id}}'
done > "$staging/image-ids.txt"
docker image inspect "${images[@]}" --format \
    '{"id":{{json .Id}},"tags":{{json .RepoTags}},"registry_digests":{{json .RepoDigests}},"os":{{json .Os}},"architecture":{{json .Architecture}},"labels":{{json (index .Config "Labels")}}}' \
    > "$staging/image-manifest.jsonl"
compressor=(gzip)
if command -v pigz >/dev/null 2>&1; then
    compressor=(pigz -p 4)
fi
docker image save "${images[@]}" | "${compressor[@]}" > "$staging/images.tar.gz"
(
    cd "$staging"
    sha256sum compose.yml README.md README.en.md README.zh-CN.md DELETE.md EPSO.md SURFGEN_COMPATIBILITY.md .env.example images.txt image-ids.txt image-manifest.jsonl images.tar.gz > SHA256SUMS
)
mv -T -- "$staging" "$output"
echo "Exported: $output"

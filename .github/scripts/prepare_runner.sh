#!/usr/bin/env bash
# For disposable GitHub-hosted Ubuntu workers only; never customer hosts.
set -euo pipefail

verify_php_packages() {
  local package source version
  while IFS=$'\t' read -r package source version; do
    # Extensions such as php8.3-amqp come from different source packages and
    # use independent version numbers. Apply the PHP fix to PHP itself only.
    if [[ "$source" == "php8.3" ]] && ! dpkg --compare-versions "$version" ge '8.3.6-0ubuntu0.24.04.13'; then
      echo "Unpatched PHP package: $package $version (source $source)" >&2
      return 1
    fi
  done
}

main() {
  if [[ "${GITHUB_ACTIONS:-}" != "true" || "${RUNNER_ENVIRONMENT:-}" != "github-hosted" ]]; then
    echo "Runner preparation requires a disposable GitHub-hosted worker." >&2
    exit 1
  fi
  . /etc/os-release
  if [[ "$ID" != "ubuntu" || "$VERSION_ID" != "24.04" ]]; then
    echo "Unsupported CI image: ${ID} ${VERSION_ID}; review before changing the baseline." >&2
    exit 1
  fi
  # Refresh distro-managed packages used for downloads and affected preinstalled PHP.
  # Only installed packages are selected; apt retains its signed repository checks.
  mapfile -t packages < <(dpkg-query -W -f='${binary:Package} ${db:Status-Status}\n' |
    awk '$2 == "installed" && ($1 ~ /^curl(:|$)/ || $1 ~ /^libcurl/ || $1 ~ /^php[0-9]/) {print $1}')
  if (( ${#packages[@]} == 0 )); then
    echo "Expected runner download packages are missing." >&2
    exit 1
  fi
  sudo apt-get update -o Acquire::Retries=3
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade --no-install-recommends -y "${packages[@]}"
  # CVE-2026-109618 / CVE-2026-109619: fail closed if the patched distro PHP is unavailable.
  # Ubuntu 24.04's curl is not affected by CVE-2026-92392; other advisories still require review.
  dpkg-query -W -f='${binary:Package}\t${source:Package}\t${source:Version}\n' "${packages[@]}" | verify_php_packages

  {
    printf '### Runner security baseline\n\n'
    printf -- '- Image: `%s` / `%s`\n' "${ImageOS:-unknown}" "${ImageVersion:-unknown}"
    printf -- '- Distribution: `%s %s`\n' "$ID" "$VERSION_ID"
    printf -- '- Download/PHP package refresh completed; checked PHP floor satisfied.\n'
    printf -- '- This package check does not certify the entire hosted image or running kernel.\n\n'
    printf '<details><summary>Post-update package versions</summary>\n\n```text\n'
    dpkg-query -W -f='${binary:Package} ${Version}\n' "${packages[@]}"
    printf '```\n</details>\n'
  } >> "${GITHUB_STEP_SUMMARY:?}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi

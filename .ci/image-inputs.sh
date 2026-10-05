#!/usr/bin/env bash
# Shared build-input selection for release allocation and moving-tag updates.
case "${1:?Expected backup-helper or runner-job}" in
  backup-helper)
    paths=(
      ':(glob)infrastructure/backup/image/*.go'
      ':(exclude,glob)infrastructure/backup/image/*_test.go'
      infrastructure/backup/image/go.mod
      infrastructure/backup/image/go.sum
      infrastructure/backup/image/Dockerfile
      infrastructure/backup/image/Dockerfile.dockerignore
    )
    cliff_paths=(--include-path 'infrastructure/backup/image/*.go'
      --exclude-path 'infrastructure/backup/image/*_test.go'
      --include-path 'infrastructure/backup/image/go.*'
      --include-path 'infrastructure/backup/image/Dockerfile*')
    dockerfile=infrastructure/backup/image/Dockerfile
    ;;
  runner-job)
    paths=(infrastructure/forgejo/runner/Dockerfile infrastructure/forgejo/runner/Dockerfile.dockerignore
      infrastructure/dns/install.sh ':(glob)infrastructure/dns/compat/*'
      package.json package-lock.json requirements-dev.txt)
    cliff_paths=(--include-path 'infrastructure/forgejo/runner/Dockerfile*'
      --include-path 'infrastructure/dns/install.sh' --include-path 'infrastructure/dns/compat/*'
      --include-path 'package.json' --include-path 'package-lock.json' --include-path 'requirements-dev.txt')
    dockerfile=infrastructure/forgejo/runner/Dockerfile
    ;;
  *) echo "Unknown image component: $1" >&2; exit 1 ;;
esac

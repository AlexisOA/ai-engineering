# syntax=docker/dockerfile:1
# check=error=true

# Session 15: a self-contained image (no bind mount needed) so the business
# backend can run in the containerized deploy exactly like the estimator does.
# Multi-stage, mirroring estimator/Dockerfile's own builder/runtime split.
#
# Deliberate trade-off: `bundle install` installs ALL groups (development +
# test), same as the pre-Session-15 image, instead of splitting a slim
# production-only gem set behind a second build target. That would need a
# second Dockerfile stage selected via `build.target` in the dev override
# (docker-compose.override.yml), which bind-mounts this same image for local
# development — keeping one gem set means the override's bind mount never hits
# a missing debug/test gem. See docs/deployment-local.md for the full
# reasoning.

ARG RUBY_VERSION=3.4.4

# =============================================================================
# Stage 1 — Builder
# =============================================================================
FROM docker.io/library/ruby:$RUBY_VERSION-slim AS builder

WORKDIR /rails

# Toolchain + runtime libraries (single layer, no recommends).
# - build-essential / git / pkg-config / libyaml-dev: native gem compilation
#   (bootsnap, debug, nokogiri).
# - libpq-dev / postgresql-client: pg driver + psql/pg_isready for debugging.
# - libvips / libjemalloc2: parity with what Rails-generated prod image carried.
# - curl: HEALTHCHECK and ad-hoc debugging.
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
        build-essential \
        curl \
        git \
        libjemalloc2 \
        libpq-dev \
        libvips \
        libyaml-dev \
        pkg-config \
        postgresql-client && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

ENV BUNDLE_PATH=/usr/local/bundle \
    BUNDLE_JOBS=4 \
    BUNDLE_RETRY=3

# Install all bundle groups (development + test included — see the trade-off
# note above). Layer-cached: only reinstalled when the Gemfile changes.
COPY Gemfile Gemfile.lock ./
RUN bundle install

# foreman is intentionally outside bundle (bin/dev convention, used by the dev
# override only — harmless to have in the image either way).
RUN gem install foreman

# Now copy the application code and precompile assets. tailwindcss-rails
# compiles CSS in pure Ruby (no Node/npm needed). assets:precompile needs SOME
# SECRET_KEY_BASE to boot the app, but not a real one — this value never ships
# in the runtime stage or the running container, which gets its own from
# compose at start time.
COPY . .

# Strip a trailing \r from every bin/* script. A checkout on Windows can carry
# CRLF line endings, which breaks the `#!/usr/bin/env ruby` shebang under Linux
# ("No such file or directory") the moment bin/rails is exec'd directly (both
# here at build time and at container startup) — this repo has no
# `bin/* text eol=lf` .gitattributes rule forcing LF regardless of host OS.
RUN sed -i 's/\r$//' bin/*

RUN RAILS_ENV=production SECRET_KEY_BASE=precompile-placeholder \
    bin/rails assets:precompile


# =============================================================================
# Stage 2 — Runtime
# =============================================================================
FROM docker.io/library/ruby:$RUBY_VERSION-slim AS runtime

WORKDIR /rails

# Runtime-only libraries — no build-essential/git/libyaml-dev/pkg-config here,
# those were only needed to compile native gem extensions in the builder stage.
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
        curl \
        libjemalloc2 \
        libpq5 \
        libvips \
        postgresql-client && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Never run as root.
RUN groupadd --system --gid 1000 rails && \
    useradd rails --uid 1000 --gid 1000 --create-home --shell /bin/bash

ENV BUNDLE_PATH=/usr/local/bundle \
    RAILS_ENV=production \
    RAILS_LOG_TO_STDOUT=1

# Pre-built gems + app code + precompiled assets, all from the builder stage.
COPY --from=builder /usr/local/bundle /usr/local/bundle
COPY --from=builder /rails /rails

RUN chown -R rails:rails /rails
USER rails

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:3000/up || exit 1

CMD ["bin/rails", "server", "-b", "0.0.0.0", "-p", "3000"]

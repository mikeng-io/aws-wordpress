# E0 apparatus image: WordPress + php-fpm, plus the tools needed to trace it.
FROM wordpress:php8.3-fpm

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        strace \
        procps \
        libfcgi-bin \
        ca-certificates \
        curl \
        less \
        jq \
        unzip; \
    rm -rf /var/lib/apt/lists/*

# wp-cli, for installing WordPress and the plugin set non-interactively.
RUN set -eux; \
    curl -fsSL -o /usr/local/bin/wp \
      https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar; \
    chmod +x /usr/local/bin/wp; \
    wp --allow-root --version

# Exactly one worker, so a trace is attributable to a single request.
# catch_workers_output keeps PHP errors visible in `docker compose logs`.
RUN { \
      echo '[www]'; \
      echo 'pm = static'; \
      echo 'pm.max_children = 1'; \
      echo 'catch_workers_output = yes'; \
      echo 'access.log = /proc/self/fd/2'; \
    } > /usr/local/etc/php-fpm.d/zz-e0.conf

COPY entrypoint-e0.sh /usr/local/bin/entrypoint-e0.sh
RUN chmod +x /usr/local/bin/entrypoint-e0.sh
ENTRYPOINT ["/usr/local/bin/entrypoint-e0.sh"]
CMD ["php-fpm"]
